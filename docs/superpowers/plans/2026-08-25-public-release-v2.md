# Public Release Prep v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare the new Mac Studio / local-TTS version of AudioBook for public release: English README, MIT license, English UI, English `.env.example`.

**Architecture:** No behavior changes. Deliverables are docs (`README.md`, `LICENSE`, `.env.example` comments) and a user-visible string translation in `app/static/index.html` plus one test assertion.

**Tech Stack:** FastAPI, MLX local TTS (qwen3/kyutai), vanilla JS PWA, uv/pyproject, pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-public-release-v2-design.md` (approved). Supersedes the v1 plan (archived on branch `archive/public-release-prep-v1`).

## Global Constraints

- Only these files change: `LICENSE` (new), `README.md` (rewrite), `.env.example` (comments), `app/static/index.html` (UI strings), `tests/test_api.py:187` (one assertion).
- French code comments/docstrings/scripts stay as-is. Only **user-visible** strings are translated.
- French Python-side error messages (`app/*.py`) stay as-is; tests asserting them (`test_api.py:181`, `test_jobs.py:167`: "indisponible") must keep passing.
- No new dependencies. No CI, no Docker, no screenshots, no feature work.
- MIT license copyright line: `Copyright (c) 2026 Lubachma`.
- Work directly on `main` (owner-approved). Commit messages in English.
- Tests: `.venv` must be reconciled first with `uv sync --extra local --extra dev` (no model download needed); run the fast suite with `uv run pytest` (engines are mocked). Never run `uv run pytest -m slow` (needs ~16 GB of models).
- No personal paths (`/Users/...`) in committed files.

---

### Task 1: Add the MIT LICENSE

**Files:**
- Create: `LICENSE`

**Interfaces:**
- Consumes: nothing.
- Produces: `LICENSE`, referenced by Task 4's README (`[MIT](LICENSE)`).

- [ ] **Step 1: Write the LICENSE file**

Create `LICENSE` with exactly this content:

```text
MIT License

Copyright (c) 2026 Lubachma

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Commit**

```bash
git add LICENSE
git commit -m "Add MIT license"
```

---

### Task 2: Translate `.env.example` comments to English

**Files:**
- Modify: `.env.example` (full rewrite with the content below)

**Interfaces:**
- Consumes: nothing.
- Produces: English configuration documentation referenced by Task 4's README.

- [ ] **Step 1: Replace `.env.example` with the English version**

Overwrite `.env.example` with exactly this content (variable names, values, ordering, and comment-out state identical to the current file — only the human-language comments change):

```text
# Copy this file to .env and adjust if needed — everything has a sensible default.

# Default engine at upload: qwen3 (local), kyutai (local) or elevenlabs (cloud).
# Note: the choice made in the UI (voice audition bench) overrides this value.
DEFAULT_ENGINE=qwen3

# Default language at upload (fr or en)
DEFAULT_LANGUAGE=fr

# Data directory (sources, texts, audios, voices). Default: <repo>/data
#DATA_DIR=

# ------------------------------------------------------------- audio output
#MP3_BITRATE=96k
#M4B_BITRATE=64k
# Loudness normalization (ffmpeg loudnorm filter); empty = disabled
#LOUDNORM=I=-18:TP=-2:LRA=11
# Pause inserted between chapters (local engines), in milliseconds
#CHAPTER_PAUSE_MS=700

# ------------------------------- local chunk quality control (whisper)
# Each segment is transcribed and compared to the source text; a score that is
# too low triggers a second take. QC_ENABLED=0 to disable.
#QC_ENABLED=1
#QC_MIN_RATIO=0.70
#QC_WHISPER_MODEL=mlx-community/whisper-small-mlx

# ------------------------------------------- local qwen3 engine (mlx-audio)
# 8-bit variant available (already downloaded): ~25% less RAM, equivalent QC
# fidelity — replace bf16 with 8bit below to try it:
#QWEN3_BASE_MODEL=mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16
#QWEN3_CUSTOM_MODEL=mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-bf16
#QWEN3_VOICE_DESIGN_MODEL=mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16
#QWEN3_TEMPERATURE=0.7

# --------------------- local kyutai engine (isolated venv .venv-kyutai, fr/en)
#KYUTAI_REPO=kyutai/tts-1.6b-en_fr
#KYUTAI_VOICE_REPO=kyutai/tts-voices
#KYUTAI_TEMP=0.6
#KYUTAI_CFG_COEF=2.0
#KYUTAI_LOAD_TIMEOUT=1800
#KYUTAI_SYNTH_TIMEOUT=900

# ----------------------------------------------- ElevenLabs (cloud, paid)
# API key (https://elevenlabs.io -> Profile -> API Key). Empty = engine hidden.
ELEVENLABS_API_KEY=
#ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM
#ELEVENLABS_MODEL_ID=eleven_multilingual_v2
#CHUNK_MAX_CHARS=4000
#VOICE_STABILITY=0.5
#VOICE_SIMILARITY_BOOST=0.75
#MONTHLY_QUOTA_CHARS=100000

# ------------------------------------------------------------------- misc
#MAX_UPLOAD_MB=100
#MIN_FREE_DISK_MB=500
```

- [ ] **Step 2: Verify structure is unchanged**

```bash
grep -cE "^#?[A-Z0-9_]+=" .env.example   # must print 29 (same variable count as before)
git diff --stat .env.example             # only .env.example changed
```

Expected: 29 assignments (same as the French version), only comments differ.

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "Translate .env.example comments to English"
```

---

### Task 3: Translate the web UI to English

**Files:**
- Modify: `app/static/index.html` (user-visible strings only)
- Test: `tests/test_api.py:187` (`assert "Livres audio" in resp.text`)

**Interfaces:**
- Consumes: nothing.
- Produces: `GET /` serves an English UI (`<title>Audiobooks</title>`, `<html lang="en">`); Media Session metadata uses `"Audiobooks"` instead of `"Livres audio"`.

Note: the file is 1056 lines — the plan does not enumerate every string. The implementer builds the complete inventory itself, per the rules below. The reviewer verifies completeness with the diff and the grep checks.

- [ ] **Step 0: Reconcile the venv, then update the failing test first (TDD)**

```bash
uv sync --extra local --extra dev
```

In `tests/test_api.py`, replace line 187 (`assert "Livres audio" in resp.text`) with:

```python
    assert "Audiobooks" in resp.text
```

- [ ] **Step 1: Run the test to verify it fails**

Run: `uv run pytest tests/test_api.py -k index -v`
Expected: FAIL — `AssertionError: assert 'Audiobooks' in ...`

- [ ] **Step 2: Build the complete string inventory and translate**

Read `app/static/index.html` in full (in chunks). Translate every **user-visible** French string to English:

- `<html lang="fr">` → `<html lang="en">`
- `<title>Livres audio</title>` and the `<h1>` → `Audiobooks` (keep the `📖 → 🎧` prefix in the h1)
- Media Session metadata (`app/static/index.html:605`): artist/album `"Livres audio"` → `"Audiobooks"`
- All form labels, select options, button labels, status badges, progress/ETA texts, empty states, section headings
- All JS-generated strings: alerts, confirm dialogs, error fallbacks, aria/title attributes, PWA manifest strings if embedded
- Locale-sensitive formatting: `toLocaleString("fr-FR")` → `toLocaleString("en-US")`; French date/number formats in user-visible output → English equivalents
- Quotation style: French « guillemets » in user-visible strings → English "quotes"

Do NOT touch:
- JS/CSS comments (they stay French per constraints)
- Logic, structure, CSS, API field names, status enum values (`extracting`, `done`…), localStorage keys
- Python files (French API error messages stay)

- [ ] **Step 3: Run the full fast suite**

Run: `uv run pytest`
Expected: all tests PASS (including the updated index test and the untouched French-message tests `test_api.py:181`, `test_jobs.py:167`).

- [ ] **Step 4: Grep for leftover French user-visible strings**

```bash
grep -nE "Livres audio|Terminé|Extraction|Conversion|Supprimer|Télécharger|Rechercher|Chapitre|Minuterie|Continuer l'écoute|En attente|Prêt|Erreur inconnue|Voix|Moteur|gratuit|Annuler|Réessayer|écouter|Écouter" app/static/index.html
```

Expected: matches only inside JS comments (verify each match is a comment). Fix any user-visible leftover and re-run step 3.

- [ ] **Step 5: Commit**

```bash
git add app/static/index.html tests/test_api.py
git commit -m "Translate web UI to English for public release"
```

---

### Task 4: Rewrite README.md in English (portfolio structure)

**Files:**
- Modify: `README.md` (full rewrite)

**Interfaces:**
- Consumes: `LICENSE` (Task 1), English `.env.example` (Task 2), English UI (Task 3).
- Produces: the public face of the repo. No screenshot references (deferred).

- [ ] **Step 1: Replace README.md with the English portfolio version**

Overwrite `README.md` with exactly this content:

````markdown
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
git clone <repo-url> && cd AudioBook
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
````

- [ ] **Step 2: Verify referenced files exist and no French remains**

```bash
ls LICENSE .env.example scripts/install.sh scripts/design_voices.py scripts/install_service.sh scripts/bench_tts.py deploy/com.audiobook.server.plist
grep -nE "Livres audio|Moteur|Voix|gratuit|Télécharger|Supprimer|chapitré|écoute|Dépannage|Utilisation" README.md || echo "README clean"
```

Expected: all files exist; `README clean` printed.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Rewrite README in English for public portfolio release"
```

---

### Task 5: Final validation

**Files:**
- None (read-only checks)

**Interfaces:**
- Consumes: all previous tasks.
- Produces: a green fast suite and a clean tree ready to push.

- [ ] **Step 1: Full fast suite**

Run: `uv run pytest`
Expected: all tests PASS (engines mocked; do not run `-m slow`).

- [ ] **Step 2: Leftover French checks**

```bash
grep -nE "Livres audio" app/static/index.html tests/test_api.py README.md .env.example || echo "no leftover brand string"
grep -nE "[«»]" app/static/index.html README.md .env.example || echo "no French quotes"
```

Expected: both clean messages (JS comments in index.html may contain French words — check any match is comment-only).

- [ ] **Step 3: No personal paths in tracked files**

```bash
git grep -nE "ludob07|/Users/" -- . || echo "no personal paths"
```

Expected: `no personal paths`.

- [ ] **Step 4: Repo state review**

```bash
git status --short
git log --oneline -8
git ls-files | grep -E "LICENSE|README|env.example|index.html"
```

Expected: clean tree; the four task commits plus spec/plan commits; files tracked.

- [ ] **Step 5: Report handoff instructions**

Summarize: repo ready; owner actions = `git push`, flip public, set description/topics (suggestions below), pin repo, capture screenshots later on the Mac Studio.
Suggested description: `Self-hosted app that turns PDFs/EPUBs into audiobooks with local TTS on Apple Silicon (Qwen3-TTS, Kyutai, MLX, FastAPI)`.
Suggested topics: `audiobook`, `tts`, `mlx`, `apple-silicon`, `fastapi`, `self-hosted`, `qwen3`, `epub`, `pdf`.

## Self-Review Notes

- Spec coverage: LICENSE (Task 1), `.env.example` (Task 2), UI + test (Task 3), README (Task 4), validation (Task 5), no-screenshots decision respected (no image references anywhere).
- Deviation from the "complete code in every step" rule: Task 3 does not enumerate every UI string — `index.html` is 1056 lines; the implementer builds the full inventory under strict rules, and the reviewer verifies with the diff + the step-4 greps. All other tasks carry verbatim content.
- Consistency: title `Audiobooks` is the same string in the test assertion (Task 3 step 0) and the translation rules; `LICENSE` copyright line identical in Tasks 1 and 4.
