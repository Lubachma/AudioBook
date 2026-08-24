"""Tests de la détection de chapitres (PDF) et de la persistance JSON."""

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from app.chapters import Chapter, load_chapters, save_chapters
from app.pdf_extract import extract_book

FILLER = "Ceci est une phrase de remplissage pour dépasser le seuil de détection de scan. "


def _pdf_with_pages(path, pages):
    """pages : liste de listes de lignes (une liste par page)."""
    c = canvas.Canvas(str(path), pagesize=LETTER)
    for lines in pages:
        y = 720
        for line in lines:
            c.drawString(72, y, line)
            y -= 20
        c.showPage()
    c.save()
    return path


def test_detects_chapter_headings(tmp_path):
    pdf = _pdf_with_pages(
        tmp_path / "livre.pdf",
        [
            ["Chapitre 1", FILLER, FILLER],
            ["Chapitre 2", FILLER, FILLER],
        ],
    )
    text, chapters = extract_book(pdf)

    assert [c.title for c in chapters] == ["Chapitre 1", "Chapitre 2"]
    assert chapters[0].offset == 0
    assert text[chapters[1].offset :].startswith("Chapitre 2")
    # Le titre reste dans le texte lu (annonce naturelle)
    assert text.startswith("Chapitre 1")


def test_preamble_before_first_chapter_becomes_debut(tmp_path):
    pdf = _pdf_with_pages(
        tmp_path / "livre.pdf",
        [
            ["Un avant-propos sans titre." , FILLER],
            ["Chapitre 1", FILLER, FILLER],
            ["Chapitre 2", FILLER, FILLER],
        ],
    )
    _, chapters = extract_book(pdf)
    assert [c.title for c in chapters] == ["Début", "Chapitre 1", "Chapitre 2"]


def test_named_sections_detected(tmp_path):
    pdf = _pdf_with_pages(
        tmp_path / "livre.pdf",
        [
            ["Prologue", FILLER, FILLER],
            ["Chapitre premier", FILLER, FILLER],
            ["Épilogue", FILLER, FILLER],
        ],
    )
    _, chapters = extract_book(pdf)
    assert [c.title for c in chapters] == ["Prologue", "Chapitre premier", "Épilogue"]


def test_no_headings_returns_empty_chapters(tmp_path):
    pdf = _pdf_with_pages(tmp_path / "livre.pdf", [[FILLER, FILLER], [FILLER, FILLER]])
    text, chapters = extract_book(pdf)
    assert chapters == []
    assert len(text) > 50


def test_roman_numerals_need_three_occurrences(tmp_path):
    # Deux romains isolés seulement : ambigus, pas de chapitres
    pdf = _pdf_with_pages(
        tmp_path / "deux.pdf",
        [["II", FILLER, FILLER], ["IV", FILLER, FILLER]],
    )
    _, chapters = extract_book(pdf)
    assert chapters == []

    # Trois romains : le motif est activé
    pdf = _pdf_with_pages(
        tmp_path / "trois.pdf",
        [["II", FILLER, FILLER], ["IV", FILLER, FILLER], ["VI", FILLER, FILLER]],
    )
    _, chapters = extract_book(pdf)
    assert [c.title for c in chapters] == ["II", "IV", "VI"]


def test_prose_line_starting_with_chapitre_ignored(tmp_path):
    """Une longue phrase commençant par « Chapitre » n'est pas un titre."""
    long_line = "Chapitre douze était le préféré de Claire car il parlait de voyages en train."
    pdf = _pdf_with_pages(
        tmp_path / "livre.pdf",
        [[long_line, FILLER], [FILLER, FILLER]],
    )
    _, chapters = extract_book(pdf)
    assert chapters == []


def test_chapters_json_roundtrip(tmp_path):
    path = tmp_path / "c.json"
    original = [Chapter("Début", 0), Chapter("Chapitre 1 — l'aube", 120)]
    save_chapters(path, original)
    assert load_chapters(path) == original


def test_chapters_json_missing_or_corrupt(tmp_path):
    assert load_chapters(tmp_path / "absent.json") == []
    bad = tmp_path / "bad.json"
    bad.write_text("{pas du json", encoding="utf-8")
    assert load_chapters(bad) == []
