#!/usr/bin/env bash
# Installe le LaunchAgent macOS : serveur lancé à l'ouverture de session, relancé s'il tombe.
# Usage : ./scripts/install_service.sh          (installe + démarre)
#         ./scripts/install_service.sh --remove (désinstalle)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.audiobook.server"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_NUM="$(id -u)"

if [[ "${1:-}" == "--remove" ]]; then
  launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Service désinstallé."
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
sed -e "s|__REPO__|$REPO|g" -e "s|__HOME__|$HOME|g" \
  "$REPO/deploy/com.audiobook.server.plist" > "$PLIST"

# Recharge idempotente. Après un bootout, launchd met parfois ~1-2 s à libérer
# le label (bootstrap échoue alors avec « error 5 ») : on retente quelques fois.
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
for attempt in 1 2 3 4 5; do
  if launchctl bootstrap "gui/$UID_NUM" "$PLIST" 2>/dev/null; then
    break
  fi
  if [[ "$attempt" == 5 ]]; then
    echo "Échec du bootstrap launchd après 5 tentatives." >&2
    exit 1
  fi
  sleep 2
done
launchctl kickstart -k "gui/$UID_NUM/$LABEL"

echo "Service installé et démarré : http://127.0.0.1:8765"
echo "Logs : ~/Library/Logs/audiobook.{out,err}.log"
echo
echo "NB : un LaunchAgent ne tourne que session ouverte. Pour un Mac serveur,"
echo "activez l'ouverture de session automatique (Réglages > Utilisateurs et groupes)."
