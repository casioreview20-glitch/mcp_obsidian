from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_brain import api, cli
from ai_brain.api import create_app


def test_default_vault_root_discovers_an_obsidian_ancestor_from_current_directory(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    service_dir = vault / "00 - AI System" / "Source Code" / "ai-brain-service"
    (vault / ".obsidian").mkdir(parents=True)
    service_dir.mkdir(parents=True)
    monkeypatch.chdir(service_dir)

    assert api._default_vault_root() == vault.resolve()


def test_cli_uses_ai_brain_vault_environment_before_current_directory(tmp_path: Path, monkeypatch):
    vault = tmp_path / "configured-vault"
    vault.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_BRAIN_VAULT", str(vault))

    args = cli._parser().parse_args(["status"])

    assert args.vault == vault


def test_run_rejects_non_loopback_host_before_creating_the_app(monkeypatch):
    monkeypatch.setenv("AI_BRAIN_HOST", "0.0.0.0")
    monkeypatch.setattr(api.uvicorn, "run", lambda *args, **kwargs: pytest.fail("must not start"))

    with pytest.raises(ValueError, match="loopback"):
        api.run()


def test_rest_api_reindexes_searches_and_blocks_path_traversal(tmp_path: Path):
    vault = tmp_path / "vault"
    note = vault / "05 - Wiki" / "AI.md"
    note.parent.mkdir(parents=True)
    note.write_text("# RAG\n\nChroma stores embeddings for relevant-note retrieval.", encoding="utf-8")
    client = TestClient(create_app(vault_root=vault, db_path=tmp_path / "chroma"))

    reindex = client.post("/reindex")
    search = client.get("/search", params={"q": "embedding Chroma", "limit": 3})
    note_response = client.get("/notes/05%20-%20Wiki/AI.md")
    traversal = client.get("/notes/../secret.txt")

    assert reindex.status_code == 200
    assert reindex.json()["indexed_files"] == 1
    assert search.status_code == 200
    assert search.json()["results"][0]["citation"] == "[[05 - Wiki/AI]]"
    assert note_response.status_code == 200
    assert "Chroma" in note_response.json()["content"]
    assert traversal.status_code == 404


def test_rest_api_requires_token_only_when_configured(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AI_BRAIN_TOKEN", "test-token")
    client = TestClient(create_app(vault_root=tmp_path / "vault", db_path=tmp_path / "chroma"))

    assert client.post("/reindex").status_code == 401
    assert client.post("/reindex", headers={"X-Local-Token": "test-token"}).status_code == 200


def test_rest_api_requires_token_for_all_vault_data_when_configured(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AI_BRAIN_TOKEN", "test-token")
    vault = tmp_path / "vault"
    note = vault / "05 - Wiki" / "AI.md"
    note.parent.mkdir(parents=True)
    note.write_text("# AI\n\nPrivate data.", encoding="utf-8")
    client = TestClient(create_app(vault_root=vault, db_path=tmp_path / "chroma"))

    assert client.get("/status").status_code == 401
    assert client.get("/search", params={"q": "private"}).status_code == 401
    assert client.get("/notes/05%20-%20Wiki/AI.md").status_code == 401
    assert client.get("/status", headers={"X-Local-Token": "test-token"}).status_code == 200


def test_rest_api_builds_a_cited_task_brief_within_budget(tmp_path: Path):
    vault = tmp_path / "vault"
    note = vault / "00 - AI System" / "Workflows" / "Debug.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Debug\n\nReproduce the failure, fix the root cause, and run regression tests.", encoding="utf-8")
    client = TestClient(create_app(vault_root=vault, db_path=tmp_path / "chroma"))
    client.post("/reindex")

    response = client.get("/brief", params={"task": "debug regression", "profile": "lean", "max_chars": 700})

    assert response.status_code == 200
    assert response.json()["char_count"] <= 700
    assert response.json()["sources"] == ["[[00 - AI System/Workflows/Debug]]"]
