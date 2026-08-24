"""Découpage du texte en morceaux compatibles avec la limite de caractères de l'API TTS.

On coupe aux frontières de phrases quand c'est possible, aux espaces sinon,
pour ne jamais couper une phrase au milieu d'un mot.
"""

import re

# Fin de phrase : . ! ? … suivi d'un espace, en tenant compte des guillemets/parenthèses fermants.
# Heuristique connue : coupe aussi après « … » sans ponctuation finale ou les
# abréviations ("M. Dupont") — l'ordre du texte est préservé, seule la prosodie
# aux frontières de chunks peut en pâtir légèrement.
_SENTENCE_END = re.compile(r"(?<=[.!?…»\"')\]])\s+")


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text) if s.strip()]


def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    """Coupe une phrase plus longue que max_chars au dernier espace disponible."""
    parts: list[str] = []
    while len(sentence) > max_chars:
        cut = sentence.rfind(" ", 0, max_chars + 1)
        if cut < max_chars // 2:  # pas d'espace exploitable -> coupe franche
            cut = max_chars
        parts.append(sentence[:cut].strip())
        sentence = sentence[cut:].strip()
    if sentence:
        parts.append(sentence)
    return parts


def chunk_text(text: str, max_chars: int = 4000) -> list[str]:
    """Regroupe les phrases en chunks de taille <= max_chars."""
    chunks: list[str] = []
    current = ""
    for sentence in split_sentences(text):
        sentence = sentence.strip()
        for piece in _split_long_sentence(sentence, max_chars):
            if current and len(current) + 1 + len(piece) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = f"{current} {piece}".strip()
    if current:
        chunks.append(current)
    return chunks


def chunk_by_chapters(text: str, chapters: list, max_chars: int) -> list[tuple[str, int]]:
    """(chunk, index_de_chapitre) — aucun chunk ne chevauche une frontière de chapitre.

    `chapters` : liste de Chapter{title, offset} triée par offset (voir chapters.py).
    Liste vide -> tout le livre est le chapitre 0. Le découpage reste déterministe,
    ce qui garantit la stabilité des indices de chunks entre deux reprises.
    """
    if not chapters:
        return [(chunk, 0) for chunk in chunk_text(text, max_chars)]
    result: list[tuple[str, int]] = []
    for idx, chapter in enumerate(chapters):
        start = chapter.offset
        end = chapters[idx + 1].offset if idx + 1 < len(chapters) else len(text)
        for chunk in chunk_text(text[start:end], max_chars):
            result.append((chunk, idx))
    return result
