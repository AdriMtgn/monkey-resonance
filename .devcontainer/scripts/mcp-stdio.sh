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

# Démarrer le MCP en mode stdio via le script standalone
exec python3 scripts/run-standalone-mcp-stdio.py