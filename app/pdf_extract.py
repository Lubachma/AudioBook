"""Extraction et nettoyage du texte d'un PDF pour la synthèse vocale.

Nettoyages appliqués :
- suppression des numéros de page isolés ;
- suppression des en-têtes/pieds de page répétés (même ligne en haut ou en bas
  d'au moins 30 % des pages) ;
- recomposition des mots coupés par une césure de fin de ligne ;
- fusion des sauts de ligne en espaces (le TTS gère mal les retours à la ligne).
"""

import re
from collections import Counter
from pathlib import Path

import pdfplumber

# En dessous de cette moyenne de caractères par page, on considère que le PDF
# est un scan sans couche texte.
MIN_CHARS_PER_PAGE = 50
# Seuil de récurrence pour considérer une ligne comme en-tête/pied répété.
REPEATED_LINE_THRESHOLD = 0.3


class ScannedPdfError(Exception):
    """PDF sans couche texte exploitable (scan d'images)."""


def extract_text(pdf_path: str | Path) -> str:
    with pdfplumber.open(str(pdf_path)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]

    if not pages:
        raise ScannedPdfError("PDF vide ou illisible.")

    if sum(len(t) for t in pages) / len(pages) < MIN_CHARS_PER_PAGE:
        raise ScannedPdfError(
            "Ce PDF semble être un scan sans couche texte (OCR non supporté)."
        )

    lines_per_page = [[line.strip() for line in text.splitlines()] for text in pages]
    repeated = _repeated_edge_lines(lines_per_page)

    pages_text = [_clean_page(lines, repeated) for lines in lines_per_page]
    return _join_lines("\n".join(t for t in pages_text if t))


def _repeated_edge_lines(lines_per_page: list[list[str]]) -> set[str]:
    """Lignes apparaissant en haut ou en bas d'au moins 30 % des pages."""
    if len(lines_per_page) < 5:
        return set()
    counts: Counter[str] = Counter()
    for lines in lines_per_page:
        edge_lines = {lines[0], lines[-1]} if lines else set()
        counts.update(line for line in edge_lines if line)
    threshold = len(lines_per_page) * REPEATED_LINE_THRESHOLD
    return {line for line, count in counts.items() if count >= threshold}


def _clean_page(lines: list[str], repeated: set[str]) -> str:
    cleaned = []
    for i, line in enumerate(lines):
        if not line:
            continue
        if re.fullmatch(r"\d{1,4}", line):  # numéro de page isolé
            continue
        if (i == 0 or i == len(lines) - 1) and line in repeated:
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _join_lines(text: str) -> str:
    # Césure de fin de ligne : "exem-\nple" -> "exemple"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # Sauts de ligne -> espaces, puis normalisation des espaces multiples
    text = text.replace("\n", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()
