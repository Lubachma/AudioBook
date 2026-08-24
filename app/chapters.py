"""Chapitres d'un livre : structure commune aux extracteurs PDF/EPUB + persistance JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Chapter:
    title: str
    offset: int  # offset caractère du début du chapitre dans le texte extrait


def save_chapters(path: str | Path, chapters: list[Chapter]) -> None:
    payload = [{"title": c.title, "offset": c.offset} for c in chapters]
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def load_chapters(path: str | Path) -> list[Chapter]:
    """Liste vide si absent/illisible (anciens livres) : traité en mono-chapitre en aval."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    chapters = []
    for row in payload:
        try:
            chapters.append(Chapter(title=str(row["title"]), offset=int(row["offset"])))
        except (KeyError, TypeError, ValueError):
            return []
    return chapters
