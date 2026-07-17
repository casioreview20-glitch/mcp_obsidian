"""Synchronize verified vault skills into Hermes' dedicated skill registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
from typing import Sequence

_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _frontmatter_value(text: str, key: str) -> str | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    match = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", text[4:end], flags=re.MULTILINE)
    return match.group(1).strip().strip('"\'') if match else None


def _default_hermes_skills_dir() -> Path:
    home = Path.home()
    hermes_home = Path.home() / "AppData" / "Local" / "hermes"
    return Path(__import__("os").environ.get("HERMES_HOME", hermes_home)) / "skills"


def sync_verified_skills(*, vault_root: Path, hermes_skills_dir: Path) -> dict[str, list[str]]:
    """Copy each standard, verified SKILL.md; draft notes never leave the vault."""

    source_root = vault_root / "00 - AI System" / "Skill Library"
    copied: list[str] = []
    skipped: list[str] = []
    if not source_root.exists():
        return {"copied": copied, "skipped": skipped}
    hermes_skills_dir.mkdir(parents=True, exist_ok=True)
    for skill_file in sorted(source_root.glob("*/SKILL.md")):
        text = skill_file.read_text(encoding="utf-8", errors="replace")
        name = _frontmatter_value(text, "name")
        status = _frontmatter_value(text, "status")
        if status != "verified" or not name or not _NAME_PATTERN.fullmatch(name):
            skipped.append(skill_file.parent.name)
            continue
        destination = hermes_skills_dir / name
        shutil.copytree(skill_file.parent, destination, dirs_exist_ok=True)
        copied.append(name)
    return {"copied": copied, "skipped": skipped}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy verified Obsidian AI Brain skills to Hermes")
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=_default_hermes_skills_dir())
    args = parser.parse_args(argv)
    print(json.dumps(sync_verified_skills(vault_root=args.vault, hermes_skills_dir=args.destination), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
