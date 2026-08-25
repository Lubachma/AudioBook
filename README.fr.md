<div align="center">

🇬🇧 <a href="README.md">English version available here</a>

# 📖 → 🎧 AudioBook

**Transformez vos PDF et EPUB en livres audio à la voix naturelle — entièrement sur votre Mac Apple Silicon.**

La synthèse vocale tourne **100 % en local** (gratuit, illimité, rien ne sort du Mac). Déposez un livre depuis n'importe quel appareil de votre réseau Tailscale, écoutez dans le navigateur ou importez le M4B chapitré dans l'app Livres. ElevenLabs reste disponible en option cloud payante.

[![CI](https://github.com/Lubachma/AudioBook/actions/workflows/ci.yml/badge.svg)](https://github.com/Lubachma/AudioBook/actions/workflows/ci.yml)
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

![Python](https://img.shields.io/badge/Python_3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![MLX](https://img.shields.io/badge/MLX-000000?logo=apple&logoColor=white)
![PWA](https://img.shields.io/badge/PWA-5A0FC8?logo=pwa&logoColor=white)

<!-- Emplacement capture d'écran — déposer une capture dans docs/assets/demo.png et décommenter :
![AudioBook — bibliothèque et lecteur](docs/assets/demo.png)
-->

</div>

## ✨ Fonctionnalités

| | Fonctionnalité |
|---|---|
| 🗣️ | **TTS 100 % local sur Apple Silicon** via MLX — pas de clé API, pas de limite d'usage, pas de compromis sur la vie privée |
| 🎤 | **Design de voix & banc d'essai** — le même extrait généré avec chaque voix candidate, voix par défaut en un clic |
| 📚 | **Ingestion PDF & EPUB** — normalisation du texte pour la voix (notes de bas de page collées, abréviations développées, numéros de chapitres), extraction de couverture, détection des chapitres |
| 🔁 | **File de jobs résiliente** — temps restant en direct, extractions parallèles, pré-écoute des segments pendant la génération, annulation/reprise sans perte, reprise automatique après redémarrage |
| ✅ | **Contrôle qualité Whisper** — chaque segment local est transcrit et comparé au texte source ; segment suspect → seconde prise ; volume normalisé avec pauses entre chapitres |
| 🎧 | **Expérience d'écoute complète** — carte « Continuer l'écoute », position synchronisée entre appareils, graduations de chapitres, sauts de ±30 s, minuterie de sommeil, commandes sur écran verrouillé (Media Session), téléchargements MP3 et M4B chapitré |
| 📱 | **PWA** — installable sur Android/iOS avec sa propre icône |
| 🔒 | **Privé par conception** — servi uniquement sur votre réseau Tailscale |

## 🎙️ Moteurs de synthèse

| Moteur | Où | Voix | Notes |
|---|---|---|---|
| `qwen3` *(défaut)* | local (MLX, mlx-audio) | voix françaises **designées** (`data/voices/`) + speakers anglophones | Qwen3-TTS-12Hz-1.7B, Apache 2.0. Le clonage lit avec la voix de référence fabriquée par `scripts/design_voices.py`. |
| `kyutai` | local (MLX, moshi-mlx, **venv isolé** `.venv-kyutai`) | voix **françaises natives** (Développeuse, Fabien, lecteurs LibriVox) + anglaises | Kyutai TTS 1.6B fr/en, CC-BY-4.0. Tourne dans un worker sous-processus car moshi-mlx exige mlx<0.27 (incompatible avec mlx-audio). |
| `elevenlabs` | cloud (payant) | voix du compte | Optionnel : clé API dans `.env`. |

## 🚀 Installation (macOS, Apple Silicon)

Prérequis : [Homebrew](https://brew.sh), `brew install uv ffmpeg`.

```bash
git clone https://github.com/Lubachma/AudioBook.git && cd AudioBook
./scripts/install.sh          # venvs + dépendances + modèles (~16 Go, long)
.venv/bin/python scripts/design_voices.py   # fabrique les narratrices françaises
```

Lancement manuel :

```bash
.venv/bin/uvicorn app.main:app --port 8765   # http://localhost:8765
```

### Démarrage automatique à l'ouverture de session (launchd)

```bash
./scripts/install_service.sh        # LaunchAgent + caffeinate (pas de veille pendant les jobs)
./scripts/install_service.sh --remove
```

Logs : `~/Library/Logs/audiobook.{out,err}.log`. Un LaunchAgent ne tourne que session ouverte → activer l'**ouverture de session automatique** (Réglages > Utilisateurs et groupes) sur un Mac qui sert de serveur.

### Accès depuis les autres appareils (Tailscale)

```bash
brew install --cask tailscale-app
open -a Tailscale          # se connecter au compte Tailscale (une fois)
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg 8765
```

L'app est alors disponible sur `https://<nom-du-mac>.<tailnet>.ts.net` pour tous les appareils du tailnet (prérequis dans la console admin Tailscale : MagicDNS et HTTPS Certificates activés). Repli sans HTTPS : servir uvicorn avec `--host $(tailscale ip -4)`.

## 📖 Utilisation

1. **Ajouter un livre** : PDF ou EPUB, par le sélecteur de fichiers ou en glisser-déposer (plusieurs fichiers d'un coup, progression d'upload affichée).
2. **L'extraction** normalise le texte pour la voix (notes de bas de page collées, « M. Dupont » → « Monsieur Dupont », « Chapitre IV » → « 4 »), récupère la **couverture** (jaquette EPUB ou première page du PDF) et détecte les chapitres (exacts pour un EPUB, par motifs pour un PDF). L'estimation affiche la durée d'audio et le temps de génération attendus.
3. **Convertir** : file d'attente visible, progression et temps restant estimé. Pendant la génération : **pré-écoute en direct** des segments déjà synthétisés (juger la voix après 2 minutes plutôt qu'après 10 heures) et bouton **annuler** (les segments faits sont conservés ; relancer la conversion reprend au même endroit). Les extractions de nouveaux livres tournent en parallèle. Un roman entier se génère typiquement en une nuit ; une interruption ou un redémarrage du Mac **reprend tout seul** sans re-synthétiser les segments déjà faits. Chaque segment local passe un **contrôle qualité whisper** (transcription comparée au texte : segment suspect → seconde prise), puis l'assemblage normalise le volume (**loudnorm**) et insère une courte pause entre les chapitres.
4. **Écouter** dans le navigateur : carte « Continuer l'écoute », position synchronisée entre appareils, graduations de chapitres, sauts de ±30 s, minuterie de sommeil (15–60 min ou fin du chapitre), liste des chapitres cliquable, contrôle de vitesse, commandes sur l'écran verrouillé (avec la couverture). Téléchargements **MP3** ou **M4B chapitré avec pochette** (app Livres sur iPhone/iPad).
5. **🔁 Autre voix** sur un livre terminé : re-synthèse avec un autre moteur/voix sans ré-upload — l'ancien audio reste écoutable pendant ce temps. La bibliothèque offre recherche, tri et vue grille des couvertures dès qu'elle grandit.

## 🛠️ Développement

```bash
uv sync --extra local --extra dev
uv run pytest                    # suite rapide (moteurs mockés)
uv run pytest -m slow -s         # intégration réelle (modèles locaux, minutes)
.venv/bin/python scripts/bench_tts.py --engine qwen3 --voice ref:claire   # vitesse/RTF
```

Structure : `app/engines/` (interface commune + qwen3/kyutai/elevenlabs), `app/audio.py` (assemblage MP3 + M4B chapitré), `app/pdf_extract.py` / `app/epub_extract.py` (texte + chapitres), `app/jobs.py` (file séquentielle, reprise par segment via `chunks.meta.json`), `app/previews.py` (banc d'essai des voix), `app/static/index.html` (UI vanilla).

## ⚙️ Configuration

Tous les réglages vivent dans `.env` (copier `.env.example` — chaque option y est documentée) : moteur et langue par défaut, bitrates audio, normalisation du volume, seuils du contrôle qualité whisper, variantes de modèles, identifiants ElevenLabs.

## 🔧 Dépannage

- **« Engine unavailable » dans l'UI** : la raison est affichée (clé API absente, `.venv-kyutai` manquant → relancer `./scripts/install.sh`).
- **Kyutai muet ou en erreur** : voir `data/logs/kyutai_worker.log`.
- **ffmpeg introuvable sous launchd** : le plist fixe le PATH Homebrew ; si le service a été installé à la main, vérifier `EnvironmentVariables.PATH`.
- **Premier livre très lent à démarrer** : chargement du modèle (~10–30 s) et, au tout premier usage, téléchargement des poids dans `~/.cache/huggingface`.
- **PDF scanné** : pas d'OCR — le livre est refusé avec un message explicite.

## 📜 Licence

[MIT](LICENSE) © 2026 Lubachma
