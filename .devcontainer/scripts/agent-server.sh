#!/usr/bin/env bash
# Démarre (ou redémarre) le serveur OpenCode DANS le container dev.
#
# Le serveur écoute sur 0.0.0.0:4096 et génère un mot de passe à chaque
# démarrage. Le mot de passe est écrit dans :
#   /base_app/.devcontainer/tmp/opencode-password
# qui est un montage bind du repo : le host le lit directement, sans passer
# par docker exec. Depuis l'hôte :
#   make agent-host
# qui exécute :
#   OPENCODE_PASSWORD=$(cat .devcontainer/tmp/opencode-password) \
#     opencode --server http://localhost:4096
#
# Toute la session (agent principal et subagents) s'exécute dans le container.
#
# Usage : bash .devcontainer/scripts/agent-server.sh   (idempotent)

set -euo pipefail

PORT="${OPENCODE_AGENT_PORT:-4096}"
HOST="${OPENCODE_AGENT_HOST:-0.0.0.0}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$REPO_ROOT/.devcontainer/tmp"
LOG_FILE="$TMP_DIR/opencode-server.log"
PASSWORD_FILE="$TMP_DIR/opencode-password"
PID_FILE="$TMP_DIR/opencode-server.pid"

mkdir -p "$TMP_DIR"

# Idempotence : si un serveur tourne déjà sur ce PID, on ne fait rien.
# Le PID vit dans le namespace du container ; un fichier PID ancien (resté
# sur le montage bind) est détecté via /proc/<pid>/cmdline pour ne pas
# confondre avec un autre process du container.
if [ -f "$PID_FILE" ]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$pid" ] && [ -r "/proc/$pid/cmdline" ] \
      && tr '\0' ' ' < "/proc/$pid/cmdline" | grep -q opencode; then
    echo "serveur opencode déjà actif (pid $pid) sur le port $PORT"
    exit 0
  fi
fi

: > "$LOG_FILE"
rm -f "$PASSWORD_FILE"

opencode serve --hostname "$HOST" --port "$PORT" > "$LOG_FILE" 2>&1 &
pid=$!
echo "$pid" > "$PID_FILE"

# Le serveur affiche "server password <mot de passe>" au démarrage : on
# l'attend (max 30s) avant de conclure à un échec.
password=""
for _ in $(seq 1 60); do
  password="$(sed -n 's/^server password //p' "$LOG_FILE" | head -n1)"
  if [ -n "$password" ]; then
    printf '%s' "$password" > "$PASSWORD_FILE"
    chmod 600 "$PASSWORD_FILE"
    break
  fi
  sleep 0.5
done

if [ ! -s "$PASSWORD_FILE" ]; then
  echo "ERREUR : le serveur opencode n'a pas démarré. Voir $LOG_FILE" >&2
  exit 1
fi

echo "serveur opencode actif sur http://$HOST:$PORT (pid $pid)"
echo "  logs         : $LOG_FILE"
echo "  mot de passe : $PASSWORD_FILE"
echo "  depuis l'hôte: make agent-host   (ou make agent-password)"
