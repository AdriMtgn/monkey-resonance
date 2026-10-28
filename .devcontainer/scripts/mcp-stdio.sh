#!/usr/bin/env bash
# Script pour démarrer le MCP Monkey Resonance via stdio pour opencode
# Compatible avec l'hôte et le container

set -euo pipefail

# Détecter si nous sommes dans le container ou sur l'hôte
if [ -d "/base_app" ]; then
    REPO_DIR="/base_app"
    APP_DIR="/base_app/app"
else
    REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
    APP_DIR="$REPO_DIR/app"
fi

cd "$REPO_DIR"

# Démarrer le MCP en mode stdio
exec python3 -c "
import sys
import os
sys.path.insert(0, '$APP_DIR')
os.chdir('$APP_DIR')

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

# Démarrer le MCP en mode stdio
from monkey_mcp.mcp import mcp
mcp.run(transport='stdio')
"