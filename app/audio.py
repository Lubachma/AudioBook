"""Écriture WAV, mesure de durées et assemblage final MP3 + M4B chapitré (ffmpeg).

Les chunks d'un livre sont soit des WAV 24 kHz mono (moteurs locaux), soit des MP3
(ElevenLabs). Le MP3 final est encodé en une passe depuis les chunks ; le M4B (AAC)
est produit dans une seconde passe depuis les mêmes chunks (pas de transcodage en
cascade), avec les chapitres en métadonnées FFMETADATA.
"""

from __future__ import annotations

import os
import subprocess
import wave
from pathlib import Path

import numpy as np

from .config import settings


class AudioError(Exception):
    """Échec de mesure ou d'assemblage audio."""


def write_wav_int16(path: str | Path, samples: np.ndarray, rate: int) -> None:
    """Écrit un WAV PCM 16 bits mono depuis des échantillons float [-1, 1]."""
    arr = np.asarray(samples, dtype=np.float32)
    if arr.ndim == 2:  # [canaux, n] -> mono
        arr = arr[0] if arr.shape[0] == 1 else arr.mean(axis=0)
    pcm = (np.clip(arr, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def wav_duration(path: str | Path) -> float:
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        return w.getnframes() / rate if rate else 0.0


def mp3_duration(path: str | Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AudioError(f"ffprobe a échoué sur {path} : {result.stderr[-300:]}")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise AudioError(f"Durée illisible pour {path} : '{result.stdout.strip()}'") from exc


def chunk_duration(path: Path) -> float:
    if path.suffix.lower() == ".wav":
        return wav_duration(path)  # exact et sans sous-processus
    return mp3_duration(path)


def _ffescape(value: str) -> str:
    """Échappement FFMETADATA : '=', ';', '#', '\\' et retour à la ligne."""
    value = value.replace("\\", "\\\\").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#")
    return value.replace("\n", "\\\n")


def build_ffmetadata(title: str, artist: str, chapters_ms: list[tuple[str, int, int]]) -> str:
    lines = [";FFMETADATA1"]
    if title:
        lines.append(f"title={_ffescape(title)}")
    if artist:
        lines.append(f"artist={_ffescape(artist)}")
    lines.append("genre=Audiobook")
    for chapter_title, start_ms, end_ms in chapters_ms:
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={start_ms}",
            f"END={end_ms}",
            f"title={_ffescape(chapter_title)}",
        ]
    return "\n".join(lines) + "\n"


def _run_ffmpeg(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace")[-500:]
        raise AudioError(f"ffmpeg a échoué (code {result.returncode}) : {stderr}")


def merge_book(
    chunk_dir: Path,
    ext: str,
    mp3_out: Path,
    m4b_out: Path,
    *,
    chapter_titles: list[str],
    chunk_chapters: list[int],
    title: str,
    artist: str = "",
) -> None:
    """Assemble chunk_0001.<ext>… en <mp3_out> et <m4b_out> (chapitré), atomiquement."""
    files = sorted(chunk_dir.glob(f"chunk_*.{ext}"))
    if not files:
        raise AudioError("Aucun chunk audio à assembler.")
    if len(files) != len(chunk_chapters):
        raise AudioError(
            f"Incohérence chunks/chapitres ({len(files)} fichiers, {len(chunk_chapters)} attendus) "
            "— supprimez le dossier de chunks et relancez la conversion."
        )

    # Timestamps de chapitres par cumul des durées de chunks.
    chapters_ms: list[tuple[str, int, int]] = []
    cursor = 0.0
    current_idx: int | None = None
    for path, chapter_idx in zip(files, chunk_chapters):
        if chapter_idx != current_idx:
            if chapters_ms:
                prev = chapters_ms[-1]
                chapters_ms[-1] = (prev[0], prev[1], int(round(cursor * 1000)))
            if 0 <= chapter_idx < len(chapter_titles):
                chapter_title = chapter_titles[chapter_idx]
            else:  # pragma: no cover - garde-fou
                chapter_title = f"Chapitre {chapter_idx + 1}"
            chapters_ms.append((chapter_title, int(round(cursor * 1000)), 0))
            current_idx = chapter_idx
        cursor += chunk_duration(path)
    if chapters_ms:
        prev = chapters_ms[-1]
        chapters_ms[-1] = (prev[0], prev[1], int(round(cursor * 1000)))

    # Chemins absolus : le demuxer concat les résout par rapport au fichier liste.
    list_file = chunk_dir / "concat.txt"
    quoted = "".join("file '{}'\n".format(str(f.resolve()).replace("'", r"'\''")) for f in files)
    list_file.write_text(quoted, encoding="utf-8")
    meta_file = chunk_dir / "chapters.ffmeta"
    meta_file.write_text(build_ffmetadata(title, artist, chapters_ms), encoding="utf-8")

    concat_input = ["-f", "concat", "-safe", "0", "-i", str(list_file)]
    tags = ["-metadata", f"title={title}", "-metadata", f"artist={artist}", "-metadata", "genre=Audiobook"]

    # MP3 : copie directe si les chunks sont déjà en MP3, sinon un seul encodage lame.
    mp3_codec = (
        ["-c", "copy"]
        if ext == "mp3"
        else ["-c:a", "libmp3lame", "-b:a", settings.mp3_bitrate, "-ac", "1"]
    )
    tmp_mp3 = mp3_out.with_name(mp3_out.stem + ".tmp.mp3")
    _run_ffmpeg(["ffmpeg", "-y", *concat_input, *mp3_codec, *tags, "-f", "mp3", str(tmp_mp3)])
    os.replace(tmp_mp3, mp3_out)

    # M4B : AAC + chapitres, container mp4/ipod compatible app Livres iOS.
    tmp_m4b = m4b_out.with_name(m4b_out.stem + ".tmp.m4b")
    _run_ffmpeg(
        [
            "ffmpeg", "-y",
            *concat_input,
            "-i", str(meta_file),
            "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1",
            "-c:a", "aac", "-b:a", settings.m4b_bitrate, "-ac", "1",
            "-movflags", "+faststart",
            *tags,
            "-f", "ipod",
            str(tmp_m4b),
        ]
    )
    os.replace(tmp_m4b, m4b_out)
