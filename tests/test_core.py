from pathlib import Path
import zipfile

import pytest

from ai_brain.core import (
    VaultPolicy,
    _split_with_overlap,
    chunk_markdown,
    is_indexable,
    normalize_vault_path,
    read_indexable_text,
    resolve_indexable_path,
    tokenize,
)


def test_tokenize_preserves_unicode_words_and_removes_stop_characters():
    assert tokenize("Naïve façade: AI works!") == ["naïve", "façade", "ai", "works"]


def test_chunk_markdown_keeps_path_and_heading_in_each_chunk():
    markdown = "# Learn Python\n\n" + "Important knowledge statement. " * 30

    chunks = chunk_markdown(markdown, relative_path="05 - Wiki/AI/Python.md", max_chars=140, overlap_chars=30)

    assert len(chunks) > 1
    assert all(chunk.relative_path == "05 - Wiki/AI/Python.md" for chunk in chunks)
    assert all("Learn Python" in chunk.text for chunk in chunks)
    assert chunks[0].chunk_index == 0


def test_policy_excludes_internal_and_obsidian_paths_but_includes_notes_and_source():
    policy = VaultPolicy(vault_root=Path("C:/vault"))

    assert is_indexable(Path("C:/vault/05 - Wiki/AI.md"), policy)
    assert is_indexable(Path("C:/vault/00 - AI System/Source Code/snippet.py"), policy)
    assert not is_indexable(Path("C:/vault/.obsidian/workspace.json"), policy)
    assert not is_indexable(Path("C:/vault/.ai-brain/chroma/file"), policy)


def test_resolve_indexable_path_returns_the_validated_resolved_file(tmp_path: Path):
    vault = tmp_path / "vault"
    note = vault / "05 - Wiki" / "AI.md"
    note.parent.mkdir(parents=True)
    note.write_text("safe", encoding="utf-8")

    assert resolve_indexable_path(note, VaultPolicy(vault_root=vault)) == note.resolve()


def test_is_indexable_rejects_case_variants_of_internal_directories(tmp_path: Path):
    vault = tmp_path / "vault"
    note = vault / ".Obsidian" / "plugin.md"
    note.parent.mkdir(parents=True)
    note.write_text("internal", encoding="utf-8")

    assert not is_indexable(note, VaultPolicy(vault_root=vault))


def test_split_with_overlap_progresses_when_word_boundary_is_shorter_than_overlap():
    pieces = _split_with_overlap(("a" * 60) + " " + ("b" * 200), limit=100, overlap=90)

    assert len(pieces) < 10
    assert all(0 < len(piece) <= 100 for piece in pieces)


def test_chunk_markdown_rejects_overlap_larger_than_effective_body_limit():
    with pytest.raises(ValueError, match="overlap_chars"):
        chunk_markdown(
            "# Long\n\nContent may repeat.",
            relative_path="05 - Wiki/Long.md",
            max_chars=80,
            overlap_chars=79,
        )


def test_chunk_markdown_keeps_every_chunk_within_the_configured_limit():
    chunks = chunk_markdown(
        "# Long\n\n" + ("long word " * 800),
        relative_path="05 - Wiki/Long.md",
        max_chars=300,
        overlap_chars=50,
    )

    assert len(chunks) > 2
    assert all(len(chunk.text) <= 300 for chunk in chunks)


def test_normalize_vault_path_rejects_traversal_outside_vault():
    root = Path("C:/vault")

    assert normalize_vault_path(root, "05 - Wiki/AI.md") == root / "05 - Wiki/AI.md"
    assert normalize_vault_path(root, "../secret.txt") is None


def test_utf16_docx_with_dtd_is_rejected_before_xml_parsing(tmp_path: Path):
    source = tmp_path / "unsafe-utf16.docx"
    xml = """<?xml version="1.0" encoding="UTF-16"?>
    <!DOCTYPE doc [<!ENTITY injected "unsafe">]>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
    <w:body><w:p><w:r><w:t>&injected;</w:t></w:r></w:p></w:body></w:document>"""
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml.encode("utf-16"))

    assert read_indexable_text(source, VaultPolicy(vault_root=tmp_path)) is None


def test_docx_with_dtd_is_rejected_before_xml_parsing(tmp_path: Path):
    source = tmp_path / "unsafe.docx"
    xml = """<!DOCTYPE doc [<!ENTITY injected \"not-trusted\">]>
    <w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">
    <w:body><w:p><w:r><w:t>&injected;</w:t></w:r></w:p></w:body></w:document>"""
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
    policy = VaultPolicy(vault_root=tmp_path)

    assert read_indexable_text(source, policy) is None


def test_docx_is_indexable_and_extracts_paragraph_text(tmp_path: Path):
    vault = tmp_path / "vault"
    document = vault / "10 - Source Data" / "Document.docx"
    document.parent.mkdir(parents=True)
    document_xml = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
    <w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">
      <w:body>
        <w:p><w:r><w:t>Local AI Brain</w:t></w:r></w:p>
        <w:p><w:r><w:t>Use verified sources only.</w:t></w:r></w:p>
      </w:body>
    </w:document>"""
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("word/document.xml", document_xml)

    policy = VaultPolicy(vault_root=vault)

    assert is_indexable(document, policy)
    assert read_indexable_text(document, policy) == "Local AI Brain\n\nUse verified sources only."
