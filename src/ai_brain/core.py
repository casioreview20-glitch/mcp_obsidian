"""Pure vault helpers: path safety, chunking, and tokenization."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import xml.etree.ElementTree as ElementTree
import zipfile

INDEXABLE_EXTENSIONS = {".md", ".txt", ".py", ".toml", ".json", ".yaml", ".yml", ".docx"}
_DEFAULT_EXCLUDED_PARTS = {".obsidian", ".ai-brain", ".git", ".venv", "__pycache__", "node_modules"}


@dataclass(frozen=True)
class VaultPolicy:
    """Vault read policy. Internal directories are never indexed."""

    vault_root: Path
    indexable_extensions: frozenset[str] = field(default_factory=lambda: frozenset(INDEXABLE_EXTENSIONS))
    excluded_parts: frozenset[str] = field(default_factory=lambda: frozenset(_DEFAULT_EXCLUDED_PARTS))
    max_file_bytes: int = 1_000_000


@dataclass(frozen=True)
class Chunk:
    relative_path: str
    chunk_index: int
    text: str


def tokenize(text: str) -> list[str]:
    """Lightweight Unicode tokenization with no model or external service dependency."""

    return re.findall(r"[^\W_]+(?:[-'][^\W_]+)*", text.lower(), flags=re.UNICODE)


def normalize_vault_path(vault_root: Path, candidate: str | Path) -> Path | None:
    """Return an absolute path within the vault, or None for an escaping path."""

    root = vault_root.resolve()
    raw = Path(candidate)
    resolved = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def resolve_indexable_path(path: Path, policy: VaultPolicy) -> Path | None:
    """Return a policy-approved resolved path so every read and stat checks the same target."""

    resolved = normalize_vault_path(policy.vault_root, path)
    if resolved is None or resolved.suffix.lower() not in policy.indexable_extensions:
        return None
    try:
        relative_parts = resolved.relative_to(policy.vault_root.resolve()).parts
    except ValueError:
        return None
    excluded_parts = {part.casefold() for part in policy.excluded_parts}
    if any(part.casefold() in excluded_parts for part in relative_parts):
        return None
    return resolved


def is_indexable(path: Path, policy: VaultPolicy) -> bool:
    """Accept only safe text files inside the vault and outside internal directories."""

    return resolve_indexable_path(path, policy) is not None


_DOCX_DOCUMENT_PATH = "word/document.xml"
_MAX_DOCX_MEMBERS = 128
_MAX_DOCX_TOTAL_UNCOMPRESSED_MULTIPLIER = 4
_MAX_DOCX_COMPRESSION_RATIO = 250
_MAX_XML_NODES = 50_000
_MAX_XML_DEPTH = 64
_XML_SCAN_ENCODINGS = ("utf-8", "utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-32-le", "utf-32-be")


def _contains_forbidden_xml_declaration(document: bytes) -> bool:
    """Detect DTD/entity declarations before parsing across common XML encodings."""

    for encoding in _XML_SCAN_ENCODINGS:
        try:
            text = document.decode(encoding)
        except UnicodeDecodeError:
            continue
        normalized = text.casefold()
        if "<!doctype" in normalized or "<!entity" in normalized:
            return True
    return False


def _extract_docx_text(path: Path, max_bytes: int) -> str | None:
    """Read DOCX within archive/XML limits and reject DTD/entity or untrusted payloads."""

    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            total_uncompressed = sum(info.file_size for info in infos)
            if len(infos) > _MAX_DOCX_MEMBERS or total_uncompressed > max_bytes * _MAX_DOCX_TOTAL_UNCOMPRESSED_MULTIPLIER:
                return None
            if any(info.file_size > max(info.compress_size, 1) * _MAX_DOCX_COMPRESSION_RATIO for info in infos):
                return None
            info = archive.getinfo(_DOCX_DOCUMENT_PATH)
            if info.file_size > max_bytes:
                return None
            document = archive.read(info)
        if _contains_forbidden_xml_declaration(document):
            return None
        root = ElementTree.fromstring(document)
    except (ElementTree.ParseError, KeyError, OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return None

    nodes = list(root.iter())
    if len(nodes) > _MAX_XML_NODES:
        return None
    stack = [(root, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > _MAX_XML_DEPTH:
            return None
        stack.extend((child, depth + 1) for child in node)

    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = [
        "".join(node.text or "" for node in paragraph.iter(f"{namespace}t")).strip()
        for paragraph in root.iter(f"{namespace}p")
    ]
    text = "\n\n".join(paragraph for paragraph in paragraphs if paragraph)
    return text or None


def read_indexable_text(path: Path, policy: VaultPolicy) -> str | None:
    """Return indexable/readable text; DOCX paragraphs are extracted locally with size limits."""

    resolved = resolve_indexable_path(path, policy)
    if resolved is None:
        return None
    try:
        if not resolved.is_file() or resolved.stat().st_size > policy.max_file_bytes:
            return None
        if resolved.suffix.lower() == ".docx":
            return _extract_docx_text(resolved, policy.max_file_bytes)
        return resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _without_frontmatter(markdown: str) -> str:
    if markdown.startswith("---\n"):
        end = markdown.find("\n---\n", 4)
        if end >= 0:
            return markdown[end + 5 :]
    return markdown


def _first_heading(markdown: str) -> str:
    match = re.search(r"^#{1,6}\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
    return match.group(1).strip() if match else "Untitled"


def _split_at_word_boundary(text: str, limit: int) -> list[str]:
    """Split text small enough to prevent one large excerpt from degrading retrieval."""

    text = text.strip()
    if not text:
        return []
    pieces: list[str] = []
    remainder = text
    while len(remainder) > limit:
        cut = remainder.rfind(" ", 0, limit + 1)
        if cut < max(1, limit // 2):
            cut = limit
        pieces.append(remainder[:cut].strip())
        remainder = remainder[cut:].strip()
    if remainder:
        pieces.append(remainder)
    return pieces


def _split_with_overlap(text: str, limit: int, overlap: int) -> list[str]:
    """Create overlapping windows while keeping every window within the limit."""

    remainder = text.strip()
    pieces: list[str] = []
    while remainder:
        if len(remainder) <= limit:
            pieces.append(remainder)
            break
        cut = remainder.rfind(" ", 0, limit + 1)
        if cut < max(1, limit // 2):
            cut = limit
        pieces.append(remainder[:cut].strip())
        safe_overlap = min(overlap, cut // 2)
        next_start = cut - safe_overlap
        remainder = remainder[next_start:].strip()
    return pieces


def chunk_markdown(
    markdown: str,
    *,
    relative_path: str,
    max_chars: int = 1_600,
    overlap_chars: int = 180,
) -> list[Chunk]:
    """Create RAG chunks with embedded source and title for reliable citations."""

    if max_chars < 80:
        raise ValueError("max_chars must be at least 80")
    if not 0 <= overlap_chars < max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")

    content = _without_frontmatter(markdown).strip()
    if not content:
        return []
    heading = _first_heading(content)
    prefix = f"Source: {relative_path}\nTitle: {heading}\n\n"
    body_limit = max_chars - len(prefix)
    if body_limit < 20:
        raise ValueError("max_chars leaves no room for the source citation")
    if not 0 <= overlap_chars < body_limit:
        raise ValueError("overlap_chars must be smaller than the effective body limit")
    bodies = _split_with_overlap(content, body_limit, overlap_chars)

    return [
        Chunk(relative_path=relative_path, chunk_index=index, text=f"{prefix}{body}")
        for index, body in enumerate(bodies)
    ]
