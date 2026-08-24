"""Tests de l'extracteur EPUB (stdlib) : spine, titres NCX, fallbacks."""

import pytest

from app.epub_extract import EpubError, extract_book

from .conftest import make_epub

BODY = "Il était une fois un livre numérique plein de texte à écouter. " * 3


def test_extracts_spine_documents_as_chapters(tmp_path):
    epub = make_epub(
        tmp_path / "livre.epub",
        [("Chapitre premier", BODY), ("Chapitre second", BODY + "La fin.")],
    )
    text, chapters = extract_book(epub)

    assert [c.title for c in chapters] == ["Chapitre premier", "Chapitre second"]
    assert chapters[0].offset == 0
    # L'offset du chapitre 2 pointe bien le début de son texte
    assert text[chapters[1].offset :].startswith("Chapitre second")
    assert "La fin." in text


def test_heading_fallback_without_ncx(tmp_path):
    epub = make_epub(
        tmp_path / "livre.epub",
        [("Le Titre H1", BODY), ("Autre Titre", BODY)],
        with_ncx=False,
    )
    _, chapters = extract_book(epub)
    # Sans table des matières, le premier <h1> du document sert de titre
    assert [c.title for c in chapters] == ["Le Titre H1", "Autre Titre"]


def test_tiny_documents_skipped(tmp_path):
    epub = make_epub(
        tmp_path / "livre.epub",
        [("Page de garde", ""), ("Chapitre 1", BODY), ("Chapitre 2", BODY)],
    )
    _, chapters = extract_book(epub)
    assert [c.title for c in chapters] == ["Chapitre 1", "Chapitre 2"]


def test_single_chapter_returns_empty_list(tmp_path):
    epub = make_epub(tmp_path / "livre.epub", [("Seul", BODY)])
    text, chapters = extract_book(epub)
    assert chapters == []
    assert len(text) > 50


def test_invalid_epub_raises(tmp_path):
    bad = tmp_path / "pas-un.epub"
    bad.write_bytes(b"pas un zip du tout")
    with pytest.raises(EpubError):
        extract_book(bad)


def test_zip_without_container_raises(tmp_path):
    import zipfile

    path = tmp_path / "vide.epub"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
    with pytest.raises(EpubError):
        extract_book(path)
