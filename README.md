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
.venv/bin/uvicorn app.main:app --port 8765   # http://localhost:8765
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
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg 8765
```

L'app est alors sur `https://<nom-du-mac>.<tailnet>.ts.net` pour tous les
appareils du tailnet (prérequis dans la console admin Tailscale : MagicDNS et
HTTPS Certificates activés). Le téléphone qui écoute doit être sur le même
compte Tailscale, ou la machine doit lui être partagée (fonction « Share »).
Repli sans HTTPS : servir uvicorn avec `--host $(tailscale ip -4)`.

## Utilisation

1. Ajouter un livre : PDF ou EPUB, par le sélecteur ou en **glisser-déposer**
   (plusieurs fichiers d'un coup, progression d'upload affichée).
2. L'extraction **normalise le texte pour la voix** (notes de bas de page
   collées, « M. Dupont » → « Monsieur Dupont », « Chapitre IV » → « 4 »…),
   récupère la **couverture** (jaquette EPUB ou 1re page du PDF) et détecte les
   chapitres (exacts pour un EPUB, par motifs pour un PDF). L'estimation
   affiche la durée d'audio et le temps de génération attendus.
3. **Convertir en audio** : file d'attente visible (« En attente »), progression
   et **temps restant estimé**. Un roman entier se génère typiquement en une
   nuit ; une interruption ou un redémarrage du Mac **reprend tout seul** sans
   re-synthétiser les segments déjà faits. Chaque segment local passe un
   **contrôle qualité** (transcription whisper comparée au texte : segment
   suspect → seconde prise), puis l'assemblage normalise le volume
   (**loudnorm**) et insère une courte pause entre les chapitres.
4. Écoute dans le navigateur : carte **« Continuer l'écoute »** en tête de page,
   **position synchronisée entre appareils**, barre de progression avec
   **graduations de chapitres**, sauts de **±30 s**, **minuterie de sommeil**
   (15-60 min ou fin du chapitre), liste des chapitres cliquable, vitesse, et
   commandes sur l'**écran verrouillé** (Media Session, avec la couverture).
   Téléchargements **MP3** / **M4B chapitré avec pochette** (app Livres iOS).
5. **🔁 Autre voix** sur un livre terminé : re-synthèse avec un autre
   moteur/voix sans ré-upload — l'ancien audio reste écoutable pendant la
   régénération. La bibliothèque offre recherche, tri et vue grille des
   couvertures dès qu'elle grandit.

L'app est une **PWA** : sur Android (Chrome ⋮ → « Installer l'application »)
ou iOS (Partager → « Sur l'écran d'accueil »), elle s'installe comme une
application avec sa propre icône.

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
