#!/usr/bin/env bash
# Démarrer le MCP Monkey Resonance en transport stdio, pour un client MCP
# (opencode, etc.) qui lance lui-même le process.
#
# Le transport par défaut du projet est HTTP streamable ; ce script le force
# en stdio via MCP_TRANSPORT=stdio. Il lance le moteur audio Pedalboard et le
# serveur MCP dans le même process.

set -euo pipefail

# Détecter si nous sommes dans le container ou sur l'hôte
if [ -d "/base_app" ]; then
    REPO_DIR="/base_app"
else
    REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
fi
APP_DIR="$REPO_DIR/app"

cd "$APP_DIR"

# stdout est réservé au protocole MCP : les logs applicatifs vont sur stderr.
export MCP_TRANSPORT=stdio
export PYTHONUNBUFFERED=1
exec python main.py --with_mcp
