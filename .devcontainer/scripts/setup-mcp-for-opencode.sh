#!/usr/bin/env bash
# Démarre le MCP Monkey Resonance et configure opencode pour l'utiliser
# en HTTP streamable (endpoint /mcp).
#
# Le MCP lui-même est lancé par start-mcp.sh (moteur audio + serveur MCP).

set -euo pipefail

REPO_ROOT="/base_app"
OPencode_CONFIG="$REPO_ROOT/.opencode/opencode.jsonc"
MCP_URL="http://127.0.0.1:${MCP_PORT:-8005}/mcp"

mkdir -p "$(dirname "$OPencode_CONFIG")"

bash "$REPO_ROOT/.devcontainer/scripts/start-mcp.sh"

# Configurer opencode pour utiliser le MCP
cat > "$OPencode_CONFIG" << EOF
{
  "\$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "monkey-resonance": {
        "type": "remote",
        "url": "$MCP_URL"
      }
    }
  }
}
EOF

echo "Configuration opencode mise à jour dans $OPencode_CONFIG"
echo "Endpoint MCP : $MCP_URL"
