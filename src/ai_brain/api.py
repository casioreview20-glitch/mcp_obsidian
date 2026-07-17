"""Local-only REST API for Obsidian AI Brain."""

from __future__ import annotations

from hmac import compare_digest
import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
import uvicorn

from .brief import build_task_brief
from .store import BrainStore


def _default_vault_root() -> Path:
    """Find an Obsidian vault from the working directory without relying on source layout."""

    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".obsidian").is_dir():
            return candidate
    raise RuntimeError("Could not locate an Obsidian vault; set AI_BRAIN_VAULT")


def _configured_paths(vault_root: Path | None, db_path: Path | None) -> tuple[Path, Path]:
    configured_root = vault_root or os.getenv("AI_BRAIN_VAULT")
    root = Path(configured_root).resolve() if configured_root else _default_vault_root()
    database = db_path or Path(os.getenv("AI_BRAIN_DB", root / ".ai-brain" / "chroma"))
    return root, database.resolve()


def create_app(*, vault_root: Path | None = None, db_path: Path | None = None) -> FastAPI:
    root, database = _configured_paths(vault_root, db_path)
    store = BrainStore(vault_root=root, db_path=database)
    local_token = os.getenv("AI_BRAIN_TOKEN")

    def require_local_token(
        x_local_token: Annotated[str | None, Header()] = None,
    ) -> None:
        if local_token and not (x_local_token and compare_digest(x_local_token, local_token)):
            raise HTTPException(status_code=401, detail="Missing or invalid X-Local-Token")

    app = FastAPI(
        title="Obsidian AI Brain API",
        version="0.1.0",
        description="Local-only REST API for an Obsidian vault, Chroma RAG, and AI agents.",
    )
    app.state.store = store

    @app.middleware("http")
    async def reject_non_loopback_clients(request: Request, call_next):
        client = request.client
        if client is None or not _is_loopback_host(client.host):
            return JSONResponse(
                status_code=403,
                content={"detail": "REST API only accepts loopback clients"},
            )
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"ok": True, "service": "obsidian-ai-brain"}

    @app.get("/status", dependencies=[Depends(require_local_token)])
    def status() -> dict[str, object]:
        return store.status()

    @app.post("/reindex", dependencies=[Depends(require_local_token)])
    def reindex() -> dict[str, object]:
        return store.reindex().to_dict()

    @app.get("/search", dependencies=[Depends(require_local_token)])
    def search(
        q: Annotated[str, Query(min_length=1, max_length=500)],
        limit: Annotated[int, Query(ge=1, le=20)] = 5,
    ) -> dict[str, object]:
        return {"query": q, "results": [result.to_dict() for result in store.search(q, limit=limit)]}

    @app.get("/brief", dependencies=[Depends(require_local_token)])
    def brief(
        task: Annotated[str, Query(min_length=1, max_length=500)],
        profile: str = "standard",
        max_chars: Annotated[int, Query(ge=400, le=12_000)] = 2_000,
    ) -> dict[str, object]:
        try:
            return build_task_brief(
                task=task,
                results=store.search(task, limit=8),
                profile=profile,
                max_chars=max_chars,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/notes/{relative_path:path}", dependencies=[Depends(require_local_token)])
    def get_note(relative_path: str) -> dict[str, object]:
        content = store.read_note(relative_path)
        if content is None:
            raise HTTPException(status_code=404, detail="No safe note was found in the vault")
        return {"path": relative_path, "content": content}

    return app


def _is_loopback_host(host: str) -> bool:
    return host in {"127.0.0.1", "::1", "localhost"}


def run() -> None:
    host = os.getenv("AI_BRAIN_HOST", "127.0.0.1")
    if not _is_loopback_host(host):
        raise ValueError("AI_BRAIN_HOST must be a loopback host: 127.0.0.1, ::1, or localhost")
    port = int(os.getenv("AI_BRAIN_PORT", "8765"))
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    run()
