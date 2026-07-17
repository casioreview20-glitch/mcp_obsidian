import json
from pathlib import Path

from ai_brain.cli import main


def test_cli_explicit_vault_does_not_require_vault_discovery(tmp_path: Path, capsys, monkeypatch):
    vault = tmp_path / "vault"
    note = vault / "05 - Wiki" / "MCP.md"
    note.parent.mkdir(parents=True)
    note.write_text("# MCP\n\nExplicit vault arguments must work outside a vault.", encoding="utf-8")
    monkeypatch.delenv("AI_BRAIN_VAULT", raising=False)
    monkeypatch.delenv("AI_BRAIN_DB", raising=False)
    monkeypatch.chdir(tmp_path)

    assert main(["--vault", str(vault), "index"]) == 0
    assert json.loads(capsys.readouterr().out)["indexed_files"] == 1


def test_cli_index_and_search_emit_json(tmp_path: Path, capsys):
    vault = tmp_path / "vault"
    note = vault / "05 - Wiki" / "MCP.md"
    note.parent.mkdir(parents=True)
    note.write_text("# MCP\n\nMCP connects AI agents to local tools.", encoding="utf-8")
    db_path = tmp_path / "chroma"

    assert main(["--vault", str(vault), "--db", str(db_path), "index"]) == 0
    indexed = json.loads(capsys.readouterr().out)
    assert indexed["indexed_files"] == 1

    assert main(["--vault", str(vault), "--db", str(db_path), "search", "AI agent tool"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert found["results"][0]["citation"] == "[[05 - Wiki/MCP]]"


def test_cli_brief_emits_compact_cited_json(tmp_path: Path, capsys):
    vault = tmp_path / "vault"
    note = vault / "05 - Wiki" / "RAG.md"
    note.parent.mkdir(parents=True)
    note.write_text("# RAG\n\nRAG retrieves compact context for coding agents.", encoding="utf-8")
    db_path = tmp_path / "chroma"
    main(["--vault", str(vault), "--db", str(db_path), "index"])
    capsys.readouterr()

    assert main([
        "--vault", str(vault), "--db", str(db_path), "brief", "coding agent context", "--profile", "lean", "--max-chars", "700"
    ]) == 0
    brief = json.loads(capsys.readouterr().out)

    assert brief["char_count"] <= 700
    assert brief["sources"] == ["[[05 - Wiki/RAG]]"]


def test_cli_import_source_copies_only_from_explicit_download_root(tmp_path: Path, capsys):
    vault = tmp_path / "vault"
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    source = downloads / "agent-notes.txt"
    source.write_text("AI agent source", encoding="utf-8")

    assert main([
        "--vault", str(vault), "import-source", str(source), "--import-root", str(downloads)
    ]) == 0
    imported = json.loads(capsys.readouterr().out)

    assert imported["relative_path"] == "10 - Source Data/Raw Documents/agent-notes.txt"
    assert (vault / imported["relative_path"]).read_text(encoding="utf-8") == "AI agent source"
