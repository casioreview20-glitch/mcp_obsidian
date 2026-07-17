from pathlib import Path

from ai_brain.hermes_sync import sync_verified_skills


def write_skill(root: Path, name: str, status: str) -> None:
    path = root / "00 - AI System" / "Skill Library" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: test\nstatus: {status}\n---\n# {name}\n",
        encoding="utf-8",
    )


def test_sync_copies_only_verified_vault_skills_to_hermes_directory(tmp_path: Path):
    vault = tmp_path / "vault"
    destination = tmp_path / "hermes-skills"
    write_skill(vault, "verified-skill", "verified")
    write_skill(vault, "draft-skill", "draft")

    report = sync_verified_skills(vault_root=vault, hermes_skills_dir=destination)

    assert report["copied"] == ["verified-skill"]
    assert (destination / "verified-skill" / "SKILL.md").exists()
    assert not (destination / "draft-skill").exists()
