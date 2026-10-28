#!/usr/bin/env bash
# Start devcontainer + opencode server (no MCP)
set -euo pipefail

echo "=== Starting Monkey Resonance devcontainer ==="
echo ""

# Start the dev container
make up-dev

# Wait for container to be ready
sleep 3

# Start opencode server
echo "=== Starting OpenCode agent server ==="
make agent-serve

echo ""
echo "✅ Devcontainer ready!"
echo "   - OpenCode server: http://localhost:4096"
echo "   - Container running: docker compose up -d mkr"
echo "   - Use 'make ask \"YOUR QUESTION\"' to talk to opencode"
echo ""
