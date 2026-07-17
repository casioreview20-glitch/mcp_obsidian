from pathlib import Path
import os
import subprocess

import pytest

from ai_brain.ingest import import_source, normalize_user_path


def test_normalize_user_path_accepts_git_bash_drive_syntax():
    assert normalize_user_path(Path("/c/Users/example/Downloads/source.docx")) == Path("C:/Users/example/Downloads/source.docx")


def test_import_source_rejects_a_destination_symlink_before_creating_outside_vault(tmp_path: Path):
    vault = tmp_path / "vault"
    downloads = tmp_path / "Downloads"
    outside = tmp_path / "outside"
    source = downloads / "guide.txt"
    downloads.mkdir()
    outside.mkdir()
    source.write_text("safe", encoding="utf-8")
    redirect = vault / "10 - Source Data"
    redirect.parent.mkdir(parents=True)
    if os.name != "nt":
        pytest.skip("Windows junction regression test")
    created = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(redirect), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip(f"Windows junction creation unavailable: {created.stderr}")

    with pytest.raises(ValueError, match="Destination"):
        import_source(vault_root=vault, source_path=source, import_root=downloads)

    assert not (outside / "Raw Documents").exists()


def test_import_source_copies_a_user_download_without_overwriting(tmp_path: Path):
    vault = tmp_path / "vault"
    downloads = tmp_path / "Downloads"
    source = downloads / "agent-notes.docx"
    downloads.mkdir()
    source.write_bytes(b"local-docx-placeholder")

    imported = import_source(vault_root=vault, source_path=source, import_root=downloads)

    assert imported.relative_path == "10 - Source Data/Raw Documents/agent-notes.docx"
    assert (vault / imported.relative_path).read_bytes() == b"local-docx-placeholder"
    with pytest.raises(ValueError, match="Downloads"):
        import_source(vault_root=vault, source_path=tmp_path / "outside.docx", import_root=downloads)
