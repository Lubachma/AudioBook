# 📖 → 🎧 Livres audio — PDF/EPUB vers voix naturelle, en local

Application familiale : on dépose un **PDF ou un EPUB** depuis n'importe quel appareil
du réseau Tailscale, le **Mac Studio** le transforme en livre audio avec une voix
la plus humaine possible, puis on l'écoute dans le navigateur ou on importe le
**M4B chapitré** dans l'app Livres (iPhone/iPad).

La synthèse tourne **entièrement en local** sur Apple Silicon (gratuit, illimité,
rien ne sort du Mac). ElevenLabs reste disponible en option cloud payante.

## Moteurs de synthèse

| Moteur | Où | Voix | Notes |
|---|---|---|---|
| `qwen3` *(défaut)* | local (MLX, mlx-audio) | voix françaises **designées** (`data/voices/`) + speakers anglophones | Qwen3-TTS-12Hz-1.7B, Apache 2.0. Le clonage lit avec la voix de référence fabriquée par `scripts/design_voices.py`. |
| `kyutai` | local (MLX, moshi-mlx, **venv isolé** `.venv-kyutai`) | voix **françaises natives** (Développeuse, Fabien, lecteurs LibriVox) + anglaises | Kyutai TTS 1.6B fr/en, CC-BY-4.0. Tourne dans un worker sous-processus car moshi-mlx exige mlx<0.27 (incompatible mlx-audio). |
| `elevenlabs` | cloud (payant) | voix du compte | Optionnel : clé API dans `.env`. |

Le **banc d'essai des voix** dans l'UI génère un même extrait avec chaque voix
candidate : on écoute, on clique « ⭐ Définir comme voix par défaut », et c'est
cette voix qui sera présélectionnée pour les prochains livres.

## Installation (macOS Apple Silicon)

Prérequis : [Homebrew](https://brew.sh), `brew install uv ffmpeg`.

```bash
git clone <repo> && cd AudioBook
./scripts/install.sh          # venvs + dépendances + modèles (~16 Go, long)
.venv/bin/python scripts/design_voices.py   # fabrique les narratrices françaises
```

Lancement manuel :

```bash
.venv/bin/uvicorn app.main:app --port 8000   # http://localhost:8000
```

### Service au démarrage (launchd)

```bash
./scripts/install_service.sh        # LaunchAgent + caffeinate (pas de veille pendant les jobs)
./scripts/install_service.sh --remove
```

Logs : `~/Library/Logs/audiobook.{out,err}.log`. Un LaunchAgent ne tourne que
session ouverte → activer l'**ouverture de session automatique** (Réglages >
Utilisateurs et groupes) sur un Mac qui sert de serveur.

### Accès depuis les autres appareils (Tailscale)

```bash
brew install --cask tailscale-app
open -a Tailscale          # se connecter au compte Tailscale (une fois)
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg 8000
```

L'app est alors sur `https://<nom-du-mac>.<tailnet>.ts.net` pour tous les
appareils du tailnet (prérequis dans la console admin Tailscale : MagicDNS et
HTTPS Certificates activés). Le téléphone qui écoute doit être sur le même
compte Tailscale, ou la machine doit lui être partagée (fonction « Share »).
Repli sans HTTPS : servir uvicorn avec `--host $(tailscale ip -4)`.

## Utilisation

1. Ouvrir l'app, choisir le fichier (PDF ou EPUB), le moteur et la voix, puis **Ajouter**.
2. L'extraction affiche le nombre de caractères (et détecte les chapitres :
   exacts pour un EPUB, par motifs « Chapitre X / Prologue / … » pour un PDF).
3. **Convertir en audio** : la synthèse tourne en tâche de fond (progression en
   temps réel). Un roman entier se génère typiquement en une nuit ; en cas
   d'interruption, la reprise ne re-synthétise que les segments manquants.
4. Écoute dans le navigateur (position mémorisée, vitesse réglable), ou
   téléchargement **MP3** / **M4B chapitré** (à ouvrir dans l'app Livres iOS).

## Migration depuis le Raspberry Pi (optionnel)

```bash
./scripts/migrate_from_pi.sh kali@<ip-du-pi> /home/kali/audiobook/data/
```

Les anciens livres restent lisibles tels quels. Ceux générés avec edge-tts
(moteur retiré) ne sont plus *re-convertibles* : les re-uploader au besoin.

## Développement

```bash
uv sync --extra local --extra dev
uv run pytest                    # suite rapide (moteurs mockés)
uv run pytest -m slow -s         # intégration réelle (modèles locaux, minutes)
.venv/bin/python scripts/bench_tts.py --engine qwen3 --voice ref:claire   # vitesse/RTF
```

Structure : `app/engines/` (interface commune + qwen3/kyutai/elevenlabs),
`app/audio.py` (assemblage MP3 + M4B chapitré), `app/pdf_extract.py` /
`app/epub_extract.py` (texte + chapitres), `app/jobs.py` (file séquentielle,
reprise par chunk avec empreinte `chunks.meta.json`), `app/previews.py`
(banc d'essai), `app/static/index.html` (UI vanilla).

## Dépannage

- **« Moteur indisponible »** dans l'UI : la raison est affichée (clé API
  absente, `.venv-kyutai` manquant → relancer `./scripts/install.sh`).
- **Kyutai muet ou en erreur** : voir `data/logs/kyutai_worker.log`.
- **ffmpeg introuvable sous launchd** : le plist fixe le PATH homebrew ; si le
  service a été installé à la main, vérifier `EnvironmentVariables.PATH`.
- **Premier livre très lent à démarrer** : chargement du modèle (~10-30 s) et,
  au tout premier usage, téléchargement des poids dans `~/.cache/huggingface`.
- **PDF scanné** : pas d'OCR — le livre est refusé avec un message explicite.
