"""MCP stdio server for Hermes, Codex, and compatible Model Context Protocol clients."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .api import _configured_paths
from .brief import build_task_brief, validate_brief_profile
from .skills import save_verified_skill
from .store import BrainStore

_MAX_QUERY_CHARS = 500
_MAX_PROFILE_CHARS = 16
_MAX_NOTE_PATH_CHARS = 500
_SKILL_FIELD_LIMITS = {
    "name": 100,
    "description": 1_000,
    "instructions": 20_000,
    "verification": 4_000,
}


def _validate_mcp_text(value: str, *, name: str, max_chars: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= max_chars:
        raise ValueError(f"{name} must contain 1 to {max_chars} characters")
    return value


def _validate_mcp_query(value: str, *, name: str) -> str:
    return _validate_mcp_text(value, name=name, max_chars=_MAX_QUERY_CHARS)


def _validate_mcp_limit(limit: int) -> int:
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    return limit


class BrainTools:
    """Transport-independent tool layer that keeps REST and MCP on the same policy."""

    def __init__(self, *, vault_root: Path, db_path: Path) -> None:
        self.store = BrainStore(vault_root=vault_root, db_path=db_path)

    def reindex_brain(self) -> dict[str, object]:
        return self.store.reindex().to_dict()

    def search_brain(self, query: str, limit: int = 5) -> dict[str, object]:
        query = _validate_mcp_query(query, name="query")
        limit = _validate_mcp_limit(limit)
        return {"query": query, "results": [result.to_dict() for result in self.store.search(query, limit=limit)]}

    def build_task_brief(
        self,
        task: str,
        profile: str = "standard",
        max_chars: int = 2_000,
    ) -> dict[str, object]:
        """Return short cited context instead of loading whole notes into an agent."""

        task = _validate_mcp_query(task, name="task")
        profile = _validate_mcp_text(profile, name="profile", max_chars=_MAX_PROFILE_CHARS)
        profile = validate_brief_profile(profile)
        return build_task_brief(
            task=task,
            results=self.store.search(task, limit=8),
            profile=profile,
            max_chars=max_chars,
        )

    def read_brain_note(self, relative_path: str) -> dict[str, object]:
        relative_path = _validate_mcp_text(
            relative_path,
            name="relative_path",
            max_chars=_MAX_NOTE_PATH_CHARS,
        )
        content = self.store.read_note(relative_path)
        return {"found": True, "path": relative_path, "content": content} if content is not None else {"found": False}

    def brain_status(self) -> dict[str, object]:
        return self.store.status()

    def capture_skill(
        self,
        *,
        name: str,
        description: str,
        instructions: str,
        verification: str,
    ) -> dict[str, object]:
        name = _validate_mcp_text(name, name="name", max_chars=_SKILL_FIELD_LIMITS["name"])
        description = _validate_mcp_text(
            description,
            name="description",
            max_chars=_SKILL_FIELD_LIMITS["description"],
        )
        instructions = _validate_mcp_text(
            instructions,
            name="instructions",
            max_chars=_SKILL_FIELD_LIMITS["instructions"],
        )
        verification = _validate_mcp_text(
            verification,
            name="verification",
            max_chars=_SKILL_FIELD_LIMITS["verification"],
        )
        path = save_verified_skill(
            vault_root=self.store.policy.vault_root,
            name=name,
            description=description,
            instructions=instructions,
            verification=verification,
        )
        report = self.store.reindex().to_dict()
        return {
            "path": path.relative_to(self.store.policy.vault_root).as_posix(),
            "reindex": report,
        }


def create_server(*, vault_root: Path | None = None, db_path: Path | None = None) -> FastMCP:
    root, database = _configured_paths(vault_root, db_path)
    tools = BrainTools(vault_root=root, db_path=database)
    server = FastMCP("obsidian-ai-brain")

    @server.tool()
    def search_brain(query: str, limit: int = 5) -> dict[str, object]:
        """Find relevant Obsidian knowledge and return [[wikilink]] sources for targeted reading."""
        return tools.search_brain(query, limit)

    @server.tool()
    def build_task_brief(
        task: str,
        profile: str = "standard",
        max_chars: int = 2_000,
    ) -> dict[str, object]:
        """Create a cited lean/standard/deep brief to reduce context and token use."""
        return tools.build_task_brief(task, profile, max_chars)

    @server.tool()
    def read_brain_note(relative_path: str) -> dict[str, object]:
        """Read one validated vault note while blocking traversal and internal directories."""
        return tools.read_brain_note(relative_path)

    @server.tool()
    def reindex_brain() -> dict[str, object]:
        """Synchronize changed notes to Chroma; only changed files are embedded again."""
        return tools.reindex_brain()

    @server.tool()
    def brain_status() -> dict[str, object]:
        """Return chunk count, vault path, and offline embedding status."""
        return tools.brain_status()

    @server.tool()
    def capture_verified_skill(
        name: str,
        description: str,
        instructions: str,
        verification: str,
    ) -> dict[str, object]:
        """After verification, save a reusable workflow to the Skill Library and reindex it."""
        return tools.capture_skill(
            name=name,
            description=description,
            instructions=instructions,
            verification=verification,
        )

    return server


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
