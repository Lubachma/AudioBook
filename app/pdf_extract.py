"""Extraction et nettoyage du texte d'un PDF pour la synthèse vocale.

Nettoyages appliqués :
- suppression des numéros de page isolés ;
- suppression des en-têtes/pieds de page répétés (même ligne en haut ou en bas
  d'au moins 30 % des pages) ;
- recomposition des mots coupés par une césure de fin de ligne ;
- fusion des sauts de ligne en espaces (le TTS gère mal les retours à la ligne).

La détection de chapitres se fait AVANT l'aplatissement, sur les lignes nettoyées :
une ligne courte du type « Chapitre 12 », « CHAPTER IV », « Prologue »… ouvre un
chapitre. Le titre reste dans le texte lu (annonce naturelle du chapitre).
"""

import re
from collections import Counter
from pathlib import Path

import pdfplumber

from .chapters import Chapter

# En dessous de cette moyenne de caractères par page, on considère que le PDF
# est un scan sans couche texte.
MIN_CHARS_PER_PAGE = 50
# Seuil de récurrence pour considérer une ligne comme en-tête/pied répété.
REPEATED_LINE_THRESHOLD = 0.3
# Au-delà, la « détection » est du bruit : on retombe en mono-chapitre.
MAX_CHAPTERS = 250
# Longueur maximale d'une ligne candidate au titre de chapitre.
MAX_HEAD_LINE_CHARS = 45

_CHAPTER_HEAD_RES = (
    re.compile(
        r"^(chapitre|chapter)\s+(\d{1,3}|[ivxlcdm]{1,7}|premier|première|un|deux|trois|"
        r"quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze|seize|"
        r"one|two|three|four|five|six|seven|eight|nine|ten)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(prologue|épilogue|epilogue|préface|preface|avant-propos|introduction|"
        r"interlude|postface)\s*[.:!]?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^((première|seconde|deuxième|troisième|quatrième|cinquième)\s+partie|"
        r"partie\s+(\d{1,2}|[ivxlcdm]{1,7})|part\s+(\d{1,2}|[ivxlcdm]{1,7}))\b",
        re.IGNORECASE,
    ),
)
# Motifs ambigus (chiffres romains seuls, « 12. ») : activés seulement s'ils
# reviennent au moins 3 fois, pour éviter les faux positifs (« V. » d'initiale…).
_ROMAN_ONLY = re.compile(r"^[IVXLCDM]{1,7}\.?$")
_NUMBER_ONLY = re.compile(r"^\d{1,3}\s*[.)]$")
_AMBIGUOUS_MIN_OCCURRENCES = 3


class ScannedPdfError(Exception):
    """PDF sans couche texte exploitable (scan d'images)."""


def extract_text(pdf_path: str | Path) -> str:
    """Texte nettoyé et aplati (compatibilité) — voir extract_book pour les chapitres."""
    return extract_book(pdf_path)[0]


def extract_book(pdf_path: str | Path) -> tuple[str, list[Chapter]]:
    """(texte aplati, chapitres avec offsets). Chapitres = [] si rien de fiable détecté."""
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
    all_lines = [line for page in pages_text if page for line in page.split("\n")]

    heads = _chapter_head_indices(all_lines)
    if len(heads) < 2 or len(heads) > MAX_CHAPTERS:
        return _join_lines("\n".join(all_lines)), []

    # Découpage en segments de lignes ; le préambule éventuel devient « Début ».
    segments: list[tuple[str, list[str]]] = []
    if heads[0] > 0:
        segments.append(("Début", all_lines[: heads[0]]))
    for i, head in enumerate(heads):
        end = heads[i + 1] if i + 1 < len(heads) else len(all_lines)
        segments.append((_clean_title(all_lines[head]), all_lines[head:end]))

    chapters: list[Chapter] = []
    parts: list[str] = []
    offset = 0
    for title, seg_lines in segments:
        seg_text = _join_lines("\n".join(seg_lines))
        if not seg_text:
            continue
        chapters.append(Chapter(title=title, offset=offset))
        parts.append(seg_text)
        offset += len(seg_text) + 1  # +1 : espace de jointure

    text = " ".join(parts)
    if len(chapters) < 2:
        return text, []
    return text, chapters


def _chapter_head_indices(lines: list[str]) -> list[int]:
    heads: list[int] = []
    ambiguous: dict[re.Pattern, list[int]] = {_ROMAN_ONLY: [], _NUMBER_ONLY: []}
    for i, line in enumerate(lines):
        if not line or len(line) > MAX_HEAD_LINE_CHARS:
            continue
        if any(pattern.match(line) for pattern in _CHAPTER_HEAD_RES):
            heads.append(i)
            continue
        for pattern, hits in ambiguous.items():
            if pattern.match(line):
                hits.append(i)
                break
    for hits in ambiguous.values():
        if len(hits) >= _AMBIGUOUS_MIN_OCCURRENCES:
            heads.extend(hits)
    return sorted(set(heads))


def _clean_title(line: str) -> str:
    return line.strip(" \t-–—:·.").strip()[:80] or "Chapitre"


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
