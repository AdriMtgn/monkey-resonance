#!/usr/bin/env bash
# Script pour configurer et lancer le MCP Monkey Resonance pour opencode
# Ce script est exécuté dans le container et configure le MCP pour être accessible
# par l'agent OpenCode via HTTP SSE.

set -euo pipefail

REPO_ROOT="/base_app"
TMP_DIR="$REPO_ROOT/.devcontainer/tmp"
LOG_FILE="$TMP_DIR/mcp.log"
PID_FILE="$TMP_DIR/mcp.pid"
OPencode_CONFIG="$REPO_ROOT/.opencode/opencode.jsonc"

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
nohup python3 -c "
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

# Démarrer le MCP en mode SSE
from monkey_mcp.mcp import mcp
mcp.run(transport='sse', mount_path='/')
" > "$LOG_FILE" 2>&1 &

pid=$!
echo "$pid" > "$PID_FILE"

echo "MCP démarré avec le PID $pid"
echo "Logs : $LOG_FILE"
echo "Le MCP est accessible sur http://127.0.0.1:8005/sse"

# Configurer opencode pour utiliser le MCP
cat > "$OPencode_CONFIG" << 'EOF'
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "monkey-resonance": {
        "type": "remote",
        "url": "http://127.0.0.1:8005/sse"
      }
    }
  }
}
EOF

echo "Configuration opencode mise à jour dans $OPencode_CONFIG"
