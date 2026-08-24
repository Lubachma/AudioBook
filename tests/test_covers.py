"""Tests de l'extraction de couvertures (PDF page 1, jaquette EPUB)."""

import io

from PIL import Image
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from app.covers import cover_path, extract_cover

from .conftest import make_epub


def _jpeg_bytes(color=(200, 30, 30), size=(300, 450)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def test_pdf_first_page_rendered_as_cover(data_dir, tmp_path):
    pdf = tmp_path / "livre.pdf"
    c = canvas.Canvas(str(pdf), pagesize=LETTER)
    c.drawString(72, 700, "Mon grand roman")
    c.showPage()
    c.save()

    out = extract_cover("job1", pdf, "pdf")

    assert out == cover_path("job1")
    with Image.open(out) as img:
        assert img.format == "JPEG"
        assert img.width <= 600 and img.height <= 900


def test_epub_cover_extracted_and_resized(data_dir, tmp_path):
    epub = make_epub(
        tmp_path / "livre.epub",
        [("Un", "Texte du chapitre un suffisant."), ("Deux", "Texte du chapitre deux.")],
        cover_jpeg=_jpeg_bytes(size=(1200, 1800)),  # grande jaquette -> redimensionnée
    )

    out = extract_cover("job2", epub, "epub")

    assert out is not None and out.exists()
    with Image.open(out) as img:
        assert img.width <= 600 and img.height <= 900


def test_epub_without_cover_returns_none(data_dir, tmp_path):
    epub = make_epub(tmp_path / "livre.epub", [("Un", "Texte."), ("Deux", "Texte.")])
    assert extract_cover("job3", epub, "epub") is None
    assert not cover_path("job3").exists()


def test_broken_source_never_raises(data_dir, tmp_path):
    broken = tmp_path / "casse.pdf"
    broken.write_bytes(b"pas un pdf")
    assert extract_cover("job4", broken, "pdf") is None
