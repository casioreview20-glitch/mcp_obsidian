"""Thin CLI for indexing and search without REST or MCP."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from .api import _configured_paths
from .brief import build_task_brief
from .ingest import import_source, normalize_user_path
from .store import BrainStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-brain", description="Obsidian AI Brain local RAG")
    parser.add_argument("--vault", type=Path, default=os.getenv("AI_BRAIN_VAULT"), help="Path to the Obsidian vault")
    parser.add_argument("--db", type=Path, default=None, help="Chroma directory (default: <vault>/.ai-brain/chroma)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("index", help="Index changed files")
    commands.add_parser("status", help="Show local status")
    search = commands.add_parser("search", help="Search the RAG index")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    brief = commands.add_parser("brief", help="Create cited context within a character budget")
    brief.add_argument("task")
    brief.add_argument("--profile", choices=("lean", "standard", "deep"), default="standard")
    brief.add_argument("--max-chars", type=int, default=2_000)
    import_command = commands.add_parser("import-source", help="Copy a Downloads source into the vault without overwriting")
    import_command.add_argument("source_path", type=Path)
    import_command.add_argument("--import-root", type=Path, default=Path.home() / "Downloads")
    note = commands.add_parser("read", help="Read a validated note")
    note.add_argument("relative_path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    configured_vault, configured_database = _configured_paths(args.vault, args.db)
    vault = normalize_user_path(configured_vault).resolve()
    database = normalize_user_path(configured_database).resolve()
    store = BrainStore(vault_root=vault, db_path=database)

    if args.command == "index":
        payload: dict[str, object] = store.reindex().to_dict()
    elif args.command == "status":
        payload = store.status()
    elif args.command == "search":
        payload = {"query": args.query, "results": [result.to_dict() for result in store.search(args.query, limit=args.limit)]}
    elif args.command == "brief":
        payload = build_task_brief(
            task=args.task,
            results=store.search(args.task, limit=8),
            profile=args.profile,
            max_chars=args.max_chars,
        )
    elif args.command == "import-source":
        payload = import_source(
            vault_root=vault,
            source_path=args.source_path,
            import_root=args.import_root,
        ).to_dict()
    else:
        content = store.read_note(args.relative_path)
        payload = {"found": content is not None, "path": args.relative_path, "content": content}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
