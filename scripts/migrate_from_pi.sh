#!/usr/bin/env bash
# Rapatrie la bibliothèque du Raspberry Pi (optionnel) : base SQLite + PDFs + audios.
# Le schéma est rétro-compatible (migrations automatiques au démarrage) ; les anciens
# livres edge-tts restent lisibles mais ne sont plus re-convertibles.
# Usage : ./scripts/migrate_from_pi.sh [utilisateur@hôte] [chemin distant]
set -euo pipefail
cd "$(dirname "$0")/.."

REMOTE="${1:-kali@raspberrypi}"
REMOTE_PATH="${2:-/home/kali/audiobook/data/}"

echo "Copie de $REMOTE:$REMOTE_PATH vers ./data/ …"
rsync -av --progress "$REMOTE:$REMOTE_PATH" ./data/
echo "Terminé. Redémarrez le serveur : les migrations de schéma s'appliquent au démarrage."
