"""Write verified skills to the vault using a small retrieval-friendly schema."""

from __future__ import annotations

import json
from pathlib import Path
import re
import unicodedata

_SECRET_PATTERN = re.compile(r"(?:api[_ -]?key|password|secret|token)\s*[:=]", re.IGNORECASE)


def _slug(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    if not slug or len(slug) > 64:
        raise ValueError("Skill name must produce a 1–64 character slug")
    return slug


def save_verified_skill(
    *,
    vault_root: Path,
    name: str,
    description: str,
    instructions: str,
    verification: str,
) -> Path:
    """Write SKILL.md while rejecting secret-like data to keep the vault out of secret storage."""

    fields = {"name": name, "description": description, "instructions": instructions, "verification": verification}
    if any(not value.strip() for value in fields.values()):
        raise ValueError("Skill requires a name, description, instructions, and verification evidence")
    if any(_SECRET_PATTERN.search(value) for value in fields.values()):
        raise ValueError("Do not store API keys, tokens, passwords, or secrets in a skill")

    slug = _slug(name)
    relative = Path("00 - AI System") / "Skill Library" / slug / "SKILL.md"
    target = vault_root / relative
    if target.exists():
        raise ValueError(f"Skill already exists: {relative.as_posix()}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "\n".join(
            [
                "---",
                f"name: {slug}",
                f"description: {json.dumps(description, ensure_ascii=False)}",
                "created_by: ai-brain",
                "status: verified",
                "---",
                "",
                f"# {name}",
                "",
                "## When to use",
                description.strip(),
                "",
                "## Verified workflow",
                instructions.strip(),
                "",
                "## Verification evidence",
                verification.strip(),
                "",
                "## Constraints",
                "- Do not include secrets, tokens, passwords, or sensitive personal data.",
                "- Update this skill only after rerunning the appropriate verification.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    index = vault_root / "00 - AI System" / "Skill Library" / "Skill Index.md"
    if not index.exists():
        index.write_text("# AI Agent Skill Index\n\n", encoding="utf-8")
    with index.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"- [[{relative.with_suffix('').as_posix()}|{name}]] — {description.strip()}\n")
    return target
