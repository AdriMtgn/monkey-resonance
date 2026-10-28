#!/usr/bin/env bash
# Démarrer le serveur MCP Monkey Resonance en mode HTTP streamable
# Ce script peut être appelé depuis l'hôte ou depuis le container

set -euo pipefail

REPO_ROOT="/base_app"
TMP_DIR="$REPO_ROOT/.devcontainer/tmp"
LOG_FILE="$TMP_DIR/mcp.log"
PID_FILE="$TMP_DIR/mcp.pid"

mkdir -p "$TMP_DIR"

# Vérifier si le MCP tourne déjà
if [ -f "$PID_FILE" ]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "MCP déjà actif (pid $pid)"
    exit 0
  fi
fi

: > "$LOG_FILE"
echo "Démarrage du MCP Monkey Resonance..."

# Exécuter le MCP avec les bonnes variables d'environnement
cd "$REPO_ROOT"
nohup python -c "
import sys
import os
sys.path.insert(0, '/base_app/app')
os.chdir('/base_app/app')

import pyo
from libs.audio_stream import AudioStream

# Démarrer le serveur pyo
s = pyo.Server()
s.boot()
s.start()

# Créer des entrées audio simulées pour le MCP
inputs = [AudioStream(0)] if pyo.pa_get_input_max_channels(0) > 0 else []

# Exposer les variables dans __main__ pour le MCP
main = type(sys)('__main__')
main.AudioStream = AudioStream
main.audio_devices = ([], [])
main.inputs = inputs

# Démarrer le MCP
from monkey_mcp.mcp import start_mcp
start_mcp()
" > "$LOG_FILE" 2>&1 &

pid=$!
echo "$pid" > "$PID_FILE"

echo "MCP démarré avec le PID $pid"
echo "Logs : $LOG_FILE"
echo "Le MCP est accessible sur http://localhost:8005"
