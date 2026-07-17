"""Local Chroma store and incremental index for Obsidian AI Brain."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import blake2b, sha256
import json
import math
from pathlib import Path
from typing import Iterable

import chromadb
from chromadb.config import Settings

from .core import (
    Chunk,
    VaultPolicy,
    chunk_markdown,
    normalize_vault_path,
    read_indexable_text,
    resolve_indexable_path,
    tokenize,
)


@dataclass(frozen=True)
class SearchResult:
    relative_path: str
    chunk_index: int
    text: str
    score: float

    @property
    def citation(self) -> str:
        return f"[[{Path(self.relative_path).with_suffix('').as_posix()}]]"

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "citation": self.citation}


@dataclass(frozen=True)
class IndexReport:
    indexed_files: int = 0
    skipped_files: int = 0
    deleted_files: int = 0
    chunks: int = 0
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "errors": list(self.errors)}


class HashEmbedder:
    """Deterministic offline embeddings with no model download or content upload."""

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension

    def embed(self, texts: Iterable[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        words = tokenize(text)
        features = words + [f"{word[i:i + 3]}" for word in words for i in range(max(0, len(word) - 2))]
        if not features:
            return vector
        for feature in features:
            digest = blake2b(feature.encode("utf-8"), digest_size=8).digest()
            number = int.from_bytes(digest, "big")
            vector[number % self.dimension] += 1.0 if number & 1 else -1.0
        magnitude = math.sqrt(sum(value * value for value in vector))
        return [value / magnitude for value in vector] if magnitude else vector


class BrainStore:
    """Private RAG index with a manifest for fast runs and no redundant indexing."""

    def __init__(self, *, vault_root: Path, db_path: Path) -> None:
        self.policy = VaultPolicy(vault_root=vault_root.resolve())
        self.db_path = db_path.resolve()
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.db_path.parent / "manifest.json"
        self.embedder = HashEmbedder()
        self.client = chromadb.PersistentClient(
            path=str(self.db_path),
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name="vault_chunks",
            metadata={"hnsw:space": "cosine"},
            embedding_function=None,
        )

    def _load_manifest(self) -> dict[str, str]:
        if not self.manifest_path.exists():
            return {}
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_manifest(self, manifest: dict[str, str]) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.manifest_path)

    def _iter_files(self) -> Iterable[Path]:
        if not self.policy.vault_root.exists():
            return []
        return (
            resolved
            for path in self.policy.vault_root.rglob("*")
            if (resolved := resolve_indexable_path(path, self.policy)) is not None and resolved.is_file()
        )

    def _remove_relative_path(self, relative_path: str) -> None:
        self.collection.delete(where={"relative_path": relative_path})

    def _upsert_chunks(self, relative_path: str, chunks: list[Chunk]) -> None:
        """Replace every chunk for a file, including when its new content has no chunks."""

        self._remove_relative_path(relative_path)
        if not chunks:
            return
        contents = [chunk.text for chunk in chunks]
        digest = sha256("\n".join(contents).encode("utf-8")).hexdigest()[:16]
        self.collection.add(
            ids=[f"{digest}-{chunk.chunk_index}" for chunk in chunks],
            documents=contents,
            embeddings=self.embedder.embed(contents),
            metadatas=[
                {"relative_path": chunk.relative_path, "chunk_index": chunk.chunk_index}
                for chunk in chunks
            ],
        )

    def reindex(self) -> IndexReport:
        """Read the vault, write only changed files, and clean up deleted notes."""

        previous = self._load_manifest()
        current: dict[str, str] = {}
        indexed = skipped = chunk_total = 0
        errors: list[str] = []

        for path in self._iter_files():
            try:
                content = read_indexable_text(path, self.policy)
                if content is None:
                    continue
                relative_path = path.relative_to(self.policy.vault_root).as_posix()
                fingerprint = sha256(content.encode("utf-8")).hexdigest()
                current[relative_path] = fingerprint
                if previous.get(relative_path) == fingerprint:
                    skipped += 1
                    continue
                chunks = chunk_markdown(content, relative_path=relative_path)
                self._upsert_chunks(relative_path, chunks)
                indexed += 1
                chunk_total += len(chunks)
            except (OSError, ValueError, RuntimeError) as exc:
                errors.append(f"{path}: {exc}")

        removed = sorted(set(previous) - set(current))
        for relative_path in removed:
            self._remove_relative_path(relative_path)
        self._save_manifest(current)
        return IndexReport(indexed, skipped, len(removed), chunk_total, tuple(errors))

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        query = query.strip()
        if not query or self.collection.count() == 0:
            return []
        count = min(max(limit, 1), min(20, self.collection.count()))
        response = self.collection.query(
            query_embeddings=self.embedder.embed([query]),
            n_results=count,
            include=["documents", "metadatas", "distances"],
        )
        documents = response.get("documents", [[]])[0] or []
        metadatas = response.get("metadatas", [[]])[0] or []
        distances = response.get("distances", [[]])[0] or []
        return [
            SearchResult(
                relative_path=str(metadata["relative_path"]),
                chunk_index=int(metadata["chunk_index"]),
                text=str(document),
                score=round(1.0 - float(distance), 4),
            )
            for document, metadata, distance in zip(documents, metadatas, distances, strict=True)
        ]

    def read_note(self, relative_path: str) -> str | None:
        path = normalize_vault_path(self.policy.vault_root, relative_path)
        if path is None:
            return None
        return read_indexable_text(path, self.policy)

    def status(self) -> dict[str, object]:
        return {
            "vault_root": str(self.policy.vault_root),
            "database_path": str(self.db_path),
            "chunks": self.collection.count(),
            "embedding": {"kind": "offline-hash", "dimension": self.embedder.dimension},
        }
