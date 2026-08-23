import pytest
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from app.pdf_extract import MIN_CHARS_PER_PAGE, ScannedPdfError, extract_text

HEADER = "Mon Livre — Chapitre 1"
BODY = (
    "Voici le contenu réel de la page avec une phrase assez longue pour "
    "dépasser largement le seuil minimal de caractères par page du test. "
    "Il y a de quoi lire, heureusement."
)


def _make_pdf(path, pages=6):
    """PDF avec en-tête répété, numéros de page et une césure."""
    c = canvas.Canvas(str(path), pagesize=LETTER)
    for i in range(1, pages + 1):
        c.drawString(72, 750, HEADER)
        c.drawString(72, 700, BODY)
        if i == 2:
            c.drawString(72, 670, "Un mot coupé par césure : infor-")
            c.drawString(72, 650, "matique retrouve son unité.")
        c.drawString(300, 40, str(i))  # numéro de page isolé
        c.showPage()
    c.save()
    return path


def test_extract_cleans_text(tmp_path):
    pdf = _make_pdf(tmp_path / "book.pdf")
    text = extract_text(pdf)

    assert "contenu réel de la page" in text
    assert HEADER not in text  # en-tête répété supprimé
    assert "informatique" in text  # césure recomposée
    assert "\n" not in text  # sauts de ligne fusionnés
    # numéros de page isolés supprimés : pas de chiffre seul entouré d'espaces
    for token in text.split():
        assert not token.isdigit()


def test_short_pdf_not_flagged_as_scanned(tmp_path):
    """Moins de 5 pages -> pas de détection d'en-têtes, mais extraction OK."""
    _make_pdf(tmp_path / "short.pdf", pages=2)
    text = extract_text(tmp_path / "short.pdf")
    assert "contenu réel" in text


def test_scanned_pdf_raises(tmp_path):
    """PDF quasi vide (images scannées simulées) -> erreur explicite."""
    c = canvas.Canvas(str(tmp_path / "scan.pdf"), pagesize=LETTER)
    for _ in range(3):
        c.drawString(72, 700, ".")  # < MIN_CHARS_PER_PAGE caractères par page
        c.showPage()
    c.save()
    with pytest.raises(ScannedPdfError, match="scan"):
        extract_text(tmp_path / "scan.pdf")


