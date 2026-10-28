#!/usr/bin/env bash
# Start/restart the app with MCP
# Auto-starts devcontainer if not running
set -euo pipefail

# Check if devcontainer is running
if [ ! -d "/base_app/.devcontainer/tmp" ]; then
    echo "⚠️  Devcontainer not running. Starting it..."
    echo ""
    bash .devcontainer/scripts/dev-start.sh
fi

# Check if opencode server is running
if [ -f "/base_app/.devcontainer/tmp/opencode-password" ]; then
    echo "✅ Devcontainer + opencode server ready"
else
    echo "⚠️  OpenCode server not running. Starting it..."
    make agent-serve
fi

echo ""
echo "=== Starting app with MCP ==="

# Kill existing app process if running
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T mkr pkill -f "python.*main.py" 2>/dev/null || true
sleep 2

# Start the app with MCP
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T -w /base_app mkr python app/main.py --with_mcp &
APP_PID=$!

echo "✅ App started (PID: $APP_PID)"
echo "   - MCP server: http://localhost:8005"
echo ""

# Reload MCP in opencode
echo "=== Reloading MCP for opencode ==="
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T -w /base_app mkr bash -c "
echo 'Stopping opencode service...'
opencode service stop 2>/dev/null || true
sleep 2
echo 'Restarting opencode service...'
opencode service start 2>/dev/null || true
echo 'MCP reloaded!'
" || echo "⚠️  MCP reload skipped (container not ready)"

echo ""
echo "🎉 App and MCP are ready!"
echo "   Use 'make ask \"your question\"' to ask opencode anything"
echo "   or open opencode TUI with 'make agent-host'"
echo ""
