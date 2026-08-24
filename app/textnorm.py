"""Normalisation du texte avant synthèse vocale (règles volontairement prudentes).

Appliquée segment par segment par les extracteurs (les offsets de chapitres sont
donc calculés sur le texte final). Objectifs :
- caractères invisibles/typographiques qui perturbent le TTS ;
- appels de notes de bas de page collés aux mots (« maison1, ») ;
- abréviations de civilité devant un nom (« M. Dupont » -> « Monsieur Dupont ») ;
- numéros de chapitres en chiffres romains (« Chapitre IV » -> « Chapitre 4 »).
"""

from __future__ import annotations

import re
import unicodedata

# Caractères à supprimer : trait d'union conditionnel, largeur nulle, BOM.
_INVISIBLE = dict.fromkeys(map(ord, "­​‌‍﻿"))
# Espaces spéciales -> espace simple (insécable, fine, etc.).
_SPACES = {ord(c): " " for c in "              　"}

# Appel de note collé à la fin d'un mot : « maison1, » / « dit-il12. »
_FOOTNOTE = re.compile(r"(?<=[a-zàâäçéèêëîïôöûùüÿœæ])\d{1,2}(?=[\s.,;:!?»)\]])")

# Civilités abrégées devant un mot capitalisé (jamais en fin de phrase).
_TITLES = (
    (re.compile(r"\bM\.\s+(?=[A-ZÀÂÉÈÊÎÔÛ])"), "Monsieur "),
    (re.compile(r"\bMme\.?\s+(?=[A-ZÀÂÉÈÊÎÔÛ])"), "Madame "),
    (re.compile(r"\bMlle\.?\s+(?=[A-ZÀÂÉÈÊÎÔÛ])"), "Mademoiselle "),
    (re.compile(r"\bDr\.?\s+(?=[A-ZÀÂÉÈÊÎÔÛ])"), "Docteur "),
    (re.compile(r"\bPr\.?\s+(?=[A-ZÀÂÉÈÊÎÔÛ])"), "Professeur "),
)

# Mot-clé insensible à la casse, mais chiffres romains en MAJUSCULES uniquement
# (sinon « partie civile » et consorts deviendraient des candidats).
_ROMAN_CHAPTER = re.compile(
    r"\b([Cc]hapitre|CHAPITRE|[Cc]hapter|CHAPTER|[Pp]artie|PARTIE|[Pp]art|PART)"
    r"\s+([IVXLCDM]{1,7})\b(?![-\w])"
)
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(roman: str) -> int | None:
    total = 0
    prev = 0
    for char in reversed(roman.upper()):
        value = _ROMAN_VALUES.get(char)
        if value is None:
            return None
        total += value if value >= prev else -value
        prev = max(prev, value)
    return total if total > 0 else None


def _replace_roman_chapter(match: re.Match) -> str:
    number = roman_to_int(match.group(2))
    if number is None or number > 200:  # au-delà, c'est probablement un mot (« MIDI »…)
        return match.group(0)
    return f"{match.group(1)} {number}"


def normalize(text: str) -> str:
    """Texte prêt pour le TTS — conserve la ponctuation et la casse du récit."""
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_INVISIBLE).translate(_SPACES)
    text = _FOOTNOTE.sub("", text)
    for pattern, replacement in _TITLES:
        text = pattern.sub(replacement, text)
    text = _ROMAN_CHAPTER.sub(_replace_roman_chapter, text)
    return re.sub(r"[ \t]+", " ", text).strip()
