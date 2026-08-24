"""Préférences persistantes modifiables depuis l'UI (table SQLite clé/valeur).

Clés utilisées :
  default_engine            moteur présélectionné à l'upload
  default_voice:<engine>    voix par défaut de chaque moteur (choisie au banc d'essai)
Ces valeurs priment sur les défauts de config.py.
"""

from __future__ import annotations

import sqlite3

from .config import settings

_SCHEMA = "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(settings.db_path, timeout=10)


def get_setting(key: str, default: str | None = None) -> str | None:
    try:
        with _connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError:  # table/base pas encore créée
        return default
    return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(_SCHEMA)
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def default_engine_name() -> str:
    return get_setting("default_engine") or settings.default_engine


def default_voice_for(engine_name: str) -> str:
    return get_setting(f"default_voice:{engine_name}") or ""
