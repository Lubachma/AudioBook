# Public Release Prep v2 — Design

Date: 2026-08-25
Status: approved by user (decisions carried over from v1 + two new ones)

## Context

The project evolved substantially on the remote (pushed from a Mac Studio):
local TTS engines (Qwen3-TTS + Kyutai via MLX), EPUB support, chaptered M4B,
covers, whisper quality control, richer player (PWA, Media Session, sleep
timer, cross-device sync), launchd service, uv/pyproject tooling. The v1 prep
(done against the old Pi 5 / Edge TTS version) is archived on branch
`archive/public-release-prep-v1`; `main` was reset to `origin/main`
(`975035f`). This v2 redoes the release prep on the new codebase.

## Decisions

Carried over from v1 (still binding):

- Target: international/anglophone portfolio → README and UI in English.
- Scope: essential only — no CI, no Docker, no refactoring, no feature work.
- License: MIT, copyright `Copyright (c) 2026 Lubachma`.
- French code comments/docstrings stay; only user-visible strings translate.
- French API error messages in Python code stay (out of scope).
- Work directly on `main` (owner-approved); English commit messages.

New for v2 (decided 2026-08-25):

- **No screenshots this round.** The README is written without image
  references; screenshots of the new UI will be added later (likely captured
  on the Mac Studio where the real library lives).
- **`.env.example` is translated to English** (it is the primary
  configuration documentation for self-hosters).

## Deliverables

1. **`LICENSE`** — same MIT text as v1 (verbatim, copyright 2026 Lubachma).
2. **`README.md`** — full English rewrite, portfolio structure, covering the
   new feature set: local TTS engines (qwen3/kyutai/elevenlabs), voice design
   bench, PDF+EPUB ingestion, whisper QC, chaptered M4B, PWA player,
   Tailscale access, install/service scripts, dev/test commands. No
   screenshot references.
3. **English UI** — `app/static/index.html` (1056 lines): all user-visible
   strings (titles, labels, buttons, status messages, Media Session metadata
   like the `"Livres audio"` artist/album at line 605, alerts, confirm
   dialogs). French JS comments and all logic stay untouched.
   `tests/test_api.py:187` asserts `"Livres audio"` in the served HTML and
   must be updated to the new English title.
4. **`.env.example`** — French comments translated to English; variable names,
   values, and structure unchanged.
5. **Validation** — `uv sync --extra local --extra dev` then `uv run pytest`
   (fast suite, engines mocked) must be green; grep checks for leftover
   French user-visible strings; no personal paths in tracked files.

## Out of scope

- Screenshots / demo GIF (deferred).
- Translating code comments, docstrings, scripts, plist, or Python-side
  error messages.
- Any feature work, CI, Docker, badges.
- The `docs/superpowers/` docs from v1 live on the archive branch; only this
  v2 spec/plan are added on `main`.

## After the repo work (owner, on GitHub)

- Push, flip the repo public, set description + topics (suggestions to be
  provided), pin the repo.
- Later: capture screenshots of the new UI on the Mac Studio and add them to
  the README.
