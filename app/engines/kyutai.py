"""Moteur local Kyutai TTS 1.6B fr/en (moshi-mlx) — via un worker en sous-processus.

moshi-mlx épingle mlx<0.27 alors que mlx-audio (moteur qwen3) exige mlx>=0.31 :
les deux ne peuvent pas cohabiter dans un même venv. Le modèle Kyutai tourne donc
dans `.venv-kyutai` (créé par scripts/install.sh) à travers scripts/kyutai_worker.py,
un daemon persistant parlant un protocole JSON ligne-à-ligne sur stdin/stdout.
Bonus : isolation mémoire complète, un crash du modèle ne tue pas l'app.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import time
from pathlib import Path

from ..config import settings
from .base import Engine, TTSError, Voice


class KyutaiEngine(Engine):
    name = "kyutai"
    label = "Kyutai TTS (local, gratuit, voix fr natives)"
    chunk_max_chars = 1500
    chunk_ext = "wav"
    is_local = True

    # Sélection curée de kyutai/tts-voices (le voice_id est le chemin dans le repo HF).
    VOICES = (
        Voice("unmute-prod-website/developpeuse-3.wav", "Développeuse (fr, F)", "kyutai", "fr"),
        Voice("unmute-prod-website/fabieng-enhanced-v2.wav", "Fabien (fr, M)", "kyutai", "fr"),
        Voice("cml-tts/fr/10087_11650_000028-0002_enhanced.wav", "Lecture CML 1 (fr)", "kyutai", "fr"),
        Voice("cml-tts/fr/10177_10625_000134-0003_enhanced.wav", "Lecture CML 2 (fr)", "kyutai", "fr"),
        Voice("unmute-prod-website/ex04_narration_longform_00001.wav", "Narration longform (en)", "kyutai", "en"),
        Voice("vctk/p225_023_enhanced.wav", "VCTK p225 (en, F)", "kyutai", "en"),
        Voice("vctk/p226_023_enhanced.wav", "VCTK p226 (en, M)", "kyutai", "en"),
    )

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._buf = bytearray()

    # ------------------------------------------------------------- découverte

    def availability(self) -> tuple[bool, str]:
        if not settings.kyutai_python.exists():
            return False, "Environnement .venv-kyutai absent — lancez scripts/install.sh"
        if not settings.kyutai_worker_script.exists():
            return False, f"Script worker introuvable : {settings.kyutai_worker_script}"
        return True, ""

    def list_voices(self) -> list[Voice]:
        return list(self.VOICES)

    def default_voice(self) -> str:
        return self.VOICES[0].voice_id

    # ------------------------------------------------------ worker subprocess

    def _spawn(self) -> subprocess.Popen:
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        stderr_log = (settings.logs_dir / "kyutai_worker.log").open("ab")
        cmd = [
            str(settings.kyutai_python),
            str(settings.kyutai_worker_script),
            "--hf-repo", settings.kyutai_repo,
            "--voice-repo", settings.kyutai_voice_repo,
            "--temp", str(settings.kyutai_temp),
            "--cfg-coef", str(settings.kyutai_cfg_coef),
        ]
        return subprocess.Popen(  # noqa: S603 - commande construite depuis la config
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_log,
            cwd=str(settings.repo_root),
        )

    def _stderr_tail(self, lines: int = 12) -> str:
        log_path = settings.logs_dir / "kyutai_worker.log"
        try:
            content = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(content[-lines:])
        except OSError:
            return ""

    def _read_line(self, timeout: float) -> dict:
        """Lit une ligne JSON du worker avec timeout (lecture non bufferisée via os.read)."""
        assert self._proc is not None and self._proc.stdout is not None
        fd = self._proc.stdout.fileno()
        deadline = time.monotonic() + timeout
        while True:
            newline = self._buf.find(b"\n")
            if newline >= 0:
                line = bytes(self._buf[:newline])
                del self._buf[: newline + 1]
                if line.strip():
                    return json.loads(line)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.unload()
                raise TTSError(f"Worker kyutai : délai dépassé ({timeout:.0f}s).")
            ready, _, _ = select.select([fd], [], [], min(remaining, 1.0))
            if ready:
                data = os.read(fd, 65536)
                if not data:
                    code = self._proc.poll()
                    self.unload()
                    raise TTSError(
                        f"Worker kyutai terminé prématurément (code {code}).\n{self._stderr_tail()}"
                    )
                self._buf.extend(data)
            elif self._proc.poll() is not None:
                code = self._proc.poll()
                self.unload()
                raise TTSError(f"Worker kyutai mort (code {code}).\n{self._stderr_tail()}")

    def load(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        ok, reason = self.availability()
        if not ok:
            raise TTSError(reason)
        self._buf.clear()
        self._proc = self._spawn()
        # Le premier démarrage peut télécharger ~4 Go de poids : délai généreux.
        ready = self._read_line(timeout=settings.kyutai_load_timeout)
        if not ready.get("ready"):
            self.unload()
            raise TTSError(f"Worker kyutai : démarrage invalide : {ready}")

    def unload(self) -> None:
        proc, self._proc = self._proc, None
        self._buf.clear()
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:  # pragma: no cover
                    proc.kill()
        finally:
            for stream in (proc.stdin, proc.stdout):
                try:
                    if stream:
                        stream.close()
                except OSError:  # pragma: no cover
                    pass

    # ---------------------------------------------------------------- synthèse

    def _synthesize(self, text: str, out_path: Path, *, voice_id: str, language: str) -> None:
        self.load()
        assert self._proc is not None and self._proc.stdin is not None
        request = {"text": text, "voice": voice_id or self.default_voice(), "out": str(out_path)}
        try:
            self._proc.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self.unload()
            raise TTSError(f"Worker kyutai injoignable : {exc}\n{self._stderr_tail()}") from exc
        response = self._read_line(timeout=settings.kyutai_synth_timeout)
        if not response.get("ok"):
            raise TTSError(f"kyutai : {response.get('error', 'erreur inconnue')}")
