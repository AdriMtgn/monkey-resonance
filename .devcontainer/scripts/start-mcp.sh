#!/usr/bin/env bash
# Démarrer le serveur MCP Monkey Resonance en HTTP streamable.
# Lance le moteur audio + le MCP dans un seul process (main.py --with_mcp) :
# endpoint http://localhost:${MCP_PORT:-8005}/mcp
# Ce script peut être appelé depuis l'hôte ou depuis le container.

set -euo pipefail

# Détecter si nous sommes dans le container ou sur l'hôte
if [ -d "/base_app" ]; then
    REPO_ROOT="/base_app"
else
    REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fi
APP_DIR="$REPO_ROOT/app"

TMP_DIR="$REPO_ROOT/.devcontainer/tmp"
LOG_FILE="$TMP_DIR/mcp.log"
PID_FILE="$TMP_DIR/mcp.pid"
PORT="${MCP_PORT:-8005}"

mkdir -p "$TMP_DIR"

# Vérifier si le MCP tourne déjà
if [ -f "$PID_FILE" ]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "MCP déjà actif (pid $pid) : http://localhost:$PORT/mcp"
    exit 0
  fi
fi

: > "$LOG_FILE"
echo "Démarrage du MCP Monkey Resonance..."

cd "$APP_DIR"
MCP_TRANSPORT=streamable-http MCP_PORT="$PORT" \
  nohup python main.py --with_mcp >> "$LOG_FILE" 2>&1 &

pid=$!
echo "$pid" > "$PID_FILE"

echo "MCP démarré avec le PID $pid"
echo "Logs : $LOG_FILE"
echo "Endpoint : http://localhost:$PORT/mcp"
