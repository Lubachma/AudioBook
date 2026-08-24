#!/usr/bin/env bash
# Installation complète sur macOS (Apple Silicon) : venvs, dépendances, modèles TTS.
# Usage : ./scripts/install.sh          (tout)
#         ./scripts/install.sh --no-models   (sans le téléchargement ~16 Go)
set -euo pipefail
cd "$(dirname "$0")/.."

DOWNLOAD_MODELS=1
[[ "${1:-}" == "--no-models" ]] && DOWNLOAD_MODELS=0

echo "==> Vérification des prérequis"
command -v brew >/dev/null || { echo "Homebrew requis : https://brew.sh"; exit 1; }
command -v uv >/dev/null || { echo "uv requis : brew install uv"; exit 1; }
command -v ffmpeg >/dev/null || { echo "ffmpeg absent — installation…"; brew install ffmpeg; }

echo "==> Environnement principal (.venv : FastAPI + mlx-audio/qwen3)"
uv sync --extra local --extra dev

echo "==> Environnement kyutai isolé (.venv-kyutai : moshi-mlx)"
# moshi-mlx épingle mlx<0.27, incompatible avec mlx-audio (mlx>=0.31) : venv séparé.
[[ -d .venv-kyutai ]] || uv venv --python 3.12 .venv-kyutai
uv pip install --python .venv-kyutai/bin/python "moshi-mlx==0.3.0" sentencepiece sphn

echo "==> Sanity check des imports"
.venv/bin/python -c "from mlx_audio.tts.utils import load_model; print('  mlx-audio OK')"
.venv-kyutai/bin/python -c "from moshi_mlx.models.tts import TTSModel; print('  moshi-mlx OK')"

if [[ $DOWNLOAD_MODELS -eq 1 ]]; then
  echo "==> Téléchargement des modèles (~16 Go au total, cache Hugging Face)"
  for repo in \
    mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16 \
    mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-bf16 \
    mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16; do
    echo "  - $repo (~4,5 Go)"
    .venv/bin/hf download "$repo" >/dev/null
  done
  echo "  - kyutai/tts-1.6b-en_fr (~4 Go)"
  .venv-kyutai/bin/python - <<'PY'
import json
from huggingface_hub import hf_hub_download
repo = "kyutai/tts-1.6b-en_fr"
cfg = json.load(open(hf_hub_download(repo, "config.json")))
hf_hub_download(repo, cfg["mimi_name"])
hf_hub_download(repo, cfg["tokenizer_name"])
hf_hub_download(repo, cfg.get("moshi_name", "model.safetensors"))
print("  kyutai OK")
PY
fi

cat <<'EOF'

Installation terminée. Étapes suivantes :
  1. Voix françaises designées :  .venv/bin/python scripts/design_voices.py
  2. Lancer le serveur (test)  :  .venv/bin/uvicorn app.main:app --port 8000
  3. Service au démarrage      :  ./scripts/install_service.sh
  4. Accès distant Tailscale   :  brew install --cask tailscale-app
     puis ouvrir Tailscale, se connecter, et :
     /Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg 8000
EOF
