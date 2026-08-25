# 📖 → 🎧 PDF & EPUB → Audiobook

Self-hosted web app that turns PDFs and EPUBs into natural-sounding audiobooks — entirely on your own Apple Silicon Mac. Upload a book from any device on your Tailscale network, listen in the browser, or import the chaptered M4B into Apple Books.

Speech synthesis runs **fully locally** (free, unlimited, nothing leaves the Mac). ElevenLabs remains available as an optional paid cloud engine.

## Features

- **100% local TTS on Apple Silicon** via MLX — no API key, no usage limits, no privacy trade-off
- **Voice design & audition bench**: generate the same excerpt with every candidate voice, set your default in one click
- **PDF and EPUB ingestion**: text normalization for speech (stuck footnotes, abbreviations expanded, chapter numerals), cover extraction, chapter detection
- **Resilient job queue**: live ETA, parallel extractions, live preview of synthesized chunks while generating, cancel/resume without losing work, automatic resume after a reboot
- **Whisper quality control**: every local chunk is transcribed and compared to the source text — suspicious chunks get a second take; loudness normalized with chapter pauses
- **Full listening experience**: continue-listening card, playback position synced across devices, chapter marks, ±30s skips, sleep timer, lock-screen controls (Media Session), MP3 and chaptered M4B downloads
- **PWA**: installable on Android/iOS with its own icon
- **Private by design**: served over your Tailscale network only

## TTS engines

| Engine | Where | Voices | Notes |
|---|---|---|---|
| `qwen3` *(default)* | local (MLX, mlx-audio) | custom-**designed French voices** (`data/voices/`) + English speakers | Qwen3-TTS-12Hz-1.7B, Apache 2.0. Cloning reads with the reference voice built by `scripts/design_voices.py`. |
| `kyutai` | local (MLX, moshi-mlx, **isolated venv** `.venv-kyutai`) | **native French voices** (Développeuse, Fabien, LibriVox readers) + English | Kyutai TTS 1.6B fr/en, CC-BY-4.0. Runs in a subprocess worker because moshi-mlx requires mlx<0.27 (incompatible with mlx-audio). |
| `elevenlabs` | cloud (paid) | account voices | Optional: API key in `.env`. |

## Installation (macOS, Apple Silicon)

Requires [Homebrew](https://brew.sh), `brew install uv ffmpeg`.

```bash
git clone https://github.com/Lubachma/AudioBook.git && cd AudioBook
./scripts/install.sh          # venvs + dependencies + models (~16 GB, long)
.venv/bin/python scripts/design_voices.py   # builds the French narrative voices
```

Run manually:

```bash
.venv/bin/uvicorn app.main:app --port 8765   # http://localhost:8765
```

### Autostart at login (launchd)

```bash
./scripts/install_service.sh        # LaunchAgent + caffeinate (no sleep during jobs)
./scripts/install_service.sh --remove
```

Logs: `~/Library/Logs/audiobook.{out,err}.log`. A LaunchAgent only runs while a session is open → enable **automatic login** (Settings > Users & Groups) on a Mac acting as a server.

### Access from other devices (Tailscale)

```bash
brew install --cask tailscale-app
open -a Tailscale          # sign in to your Tailscale account (once)
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg 8765
```

The app is then available at `https://<mac-name>.<tailnet>.ts.net` for every device on the tailnet (requires MagicDNS and HTTPS Certificates enabled in the Tailscale admin console). Fallback without HTTPS: serve uvicorn with `--host $(tailscale ip -4)`.

## Usage

1. **Add a book**: PDF or EPUB, via the file picker or drag & drop (multiple files at once, with upload progress).
2. **Extraction** normalizes the text for speech (footnote markers, `M. Dupont` → `Monsieur Dupont`, `Chapitre IV` → `4`), grabs the **cover** (EPUB jacket or PDF first page) and detects chapters (exact for EPUB, pattern-based for PDF). The estimate shows expected audio length and generation time.
3. **Convert**: visible queue, progress and ETA. During generation: **live preview** of already-synthesized chunks (judge the voice after 2 minutes instead of 10 hours) and a **cancel** button (finished chunks are kept; converting again resumes where it stopped). Extractions of new books run in parallel. A full novel typically generates overnight; an interruption or a Mac reboot **resumes automatically** without re-synthesizing finished chunks. Each local chunk passes **whisper quality control** (transcription compared to the text: suspicious chunk → second take), then assembly normalizes loudness (**loudnorm**) and inserts a short pause between chapters.
4. **Listen** in the browser: continue-listening card, cross-device position sync, chapter marks, ±30s skips, sleep timer (15–60 min or end of chapter), clickable chapter list, speed control, lock-screen controls (with cover art). Downloads as **MP3** or **chaptered M4B with cover** (Apple Books on iPhone/iPad).
5. **🔁 Another voice** on a finished book: re-synthesize with a different engine/voice without re-uploading — the old audio stays playable meanwhile. The library offers search, sort, and a cover grid view as it grows.

## Development

```bash
uv sync --extra local --extra dev
uv run pytest                    # fast suite (engines mocked)
uv run pytest -m slow -s         # real integration (local models, minutes)
.venv/bin/python scripts/bench_tts.py --engine qwen3 --voice ref:claire   # speed/RTF
```

Structure: `app/engines/` (common interface + qwen3/kyutai/elevenlabs), `app/audio.py` (MP3 + chaptered M4B assembly), `app/pdf_extract.py` / `app/epub_extract.py` (text + chapters), `app/jobs.py` (sequential queue, per-chunk resume via `chunks.meta.json`), `app/previews.py` (voice bench), `app/static/index.html` (vanilla UI).

## Configuration

All settings live in `.env` (copy `.env.example` — every option is documented there): default engine and language, audio bitrates, loudness normalization, whisper QC thresholds, model variants, ElevenLabs credentials.

## Troubleshooting

- **"Engine unavailable" in the UI**: the reason is shown (missing API key, missing `.venv-kyutai` → re-run `./scripts/install.sh`).
- **Kyutai silent or erroring**: see `data/logs/kyutai_worker.log`.
- **ffmpeg not found under launchd**: the plist sets the Homebrew PATH; if the service was installed manually, check `EnvironmentVariables.PATH`.
- **First book very slow to start**: model loading (~10–30 s) and, on first use, weight download into `~/.cache/huggingface`.
- **Scanned PDF**: no OCR — the book is rejected with an explicit message.

## License

[MIT](LICENSE) © 2026 Lubachma
