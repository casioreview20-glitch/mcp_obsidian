from pathlib import Path
import zipfile

from ai_brain import store as store_module
from ai_brain.store import BrainStore


def write_note(vault: Path, relative_path: str, text: str) -> Path:
    path = vault / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_store_disables_chroma_anonymized_telemetry(tmp_path: Path, monkeypatch):
    observed: dict[str, object] = {}

    class FakeClient:
        def get_or_create_collection(self, **_kwargs):
            return object()

    def persistent_client(**kwargs):
        observed.update(kwargs)
        return FakeClient()

    monkeypatch.setattr(store_module.chromadb, "PersistentClient", persistent_client)

    BrainStore(vault_root=tmp_path / "vault", db_path=tmp_path / "chroma")

    assert observed["settings"].anonymized_telemetry is False


def test_reindex_and_search_return_ranked_citations(tmp_path: Path):
    vault = tmp_path / "vault"
    write_note(vault, "05 - Wiki/AI/Python.md", "# Python\n\nFastAPI helps build REST APIs with Python.")
    write_note(vault, "05 - Wiki/AI/Obsidian.md", "# Obsidian\n\nObsidian stores local Markdown notes.")
    store = BrainStore(vault_root=vault, db_path=tmp_path / "chroma")

    report = store.reindex()
    results = store.search("build REST API with Python", limit=3)

    assert report.indexed_files == 2
    assert results[0].relative_path == "05 - Wiki/AI/Python.md"
    assert results[0].citation == "[[05 - Wiki/AI/Python]]"
    assert "FastAPI" in results[0].text


def test_reindex_skips_unchanged_files_and_removes_deleted_notes(tmp_path: Path):
    vault = tmp_path / "vault"
    note = write_note(vault, "09 - Inbox/Note.md", "# Quick\n\nAn idea needs processing.")
    store = BrainStore(vault_root=vault, db_path=tmp_path / "chroma")

    first = store.reindex()
    second = store.reindex()
    note.unlink()
    third = store.reindex()

    assert first.indexed_files == 1
    assert second.skipped_files == 1
    assert third.deleted_files == 1
    assert store.search("idea", limit=3) == []


def test_reindex_removes_chunks_when_an_indexed_note_becomes_empty(tmp_path: Path):
    vault = tmp_path / "vault"
    note = write_note(vault, "05 - Wiki/Temporary.md", "# Temporary\n\nOld content must not remain stored.")
    store = BrainStore(vault_root=vault, db_path=tmp_path / "chroma")
    store.reindex()

    note.write_text("\n \n", encoding="utf-8")
    report = store.reindex()

    assert report.indexed_files == 1
    assert store.search("old stored content", limit=3) == []


def test_reindex_docx_uses_extracted_text_for_search_and_safe_read(tmp_path: Path):
    vault = tmp_path / "vault"
    source = vault / "10 - Source Data" / "Prompt OS.docx"
    source.parent.mkdir(parents=True)
    xml = """<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">
    <w:body><w:p><w:r><w:t>Local Agent Prompt</w:t></w:r></w:p>
    <w:p><w:r><w:t>Skills reduce context for coding agents.</w:t></w:r></w:p></w:body></w:document>"""
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
    store = BrainStore(vault_root=vault, db_path=tmp_path / "chroma")

    report = store.reindex()
    results = store.search("skills reduce context", limit=3)

    assert report.indexed_files == 1
    assert results[0].relative_path == "10 - Source Data/Prompt OS.docx"
    assert store.read_note("10 - Source Data/Prompt OS.docx") == (
        "Local Agent Prompt\n\nSkills reduce context for coding agents."
    )
