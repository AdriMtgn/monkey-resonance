#!/usr/bin/env bash
# Ask opencode a question (runs a command in the container via opencode)
set -euo pipefail

if [ -z "$1" ]; then
    echo "Usage: ask-opencode \"your question\""
    exit 1
fi

# Check if devcontainer is running
if [ ! -d "/base_app/.devcontainer/tmp" ]; then
    echo "⚠️  Devcontainer not running. Starting it..."
    bash .devcontainer/scripts/dev-start.sh
fi

# Check if opencode is running
if [ ! -f "/base_app/.devcontainer/tmp/opencode-password" ]; then
    echo "⚠️  OpenCode server not running. Starting it..."
    make agent-serve
fi

echo "=== Asking opencode ==="
echo "Question: $1"
echo ""

# Run the question via opencode MCP
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T -w /base_app mkr bash -c "
# Check if MCP is available and tools work
python3 -c \"
import asyncio
from mcp import ClientSession
import httpx

async def check_mcp():
    try:
        async with httpx.AsyncClient() as client:
            # Test MCP connection
            resp = await client.post('http://127.0.0.1:8005/mcp',
                headers={'Accept': 'application/json, text/event-stream'},
                json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}})
            if resp.status_code == 200:
                print('✅ MCP connected')
            else:
                print(f'⚠️  MCP response: {resp.status_code}')
    except Exception as e:
        print(f'⚠️  MCP connection: {e}')

asyncio.run(check_mcp())
\"
" 2>/dev/null || true

echo ""
echo "📝 To interact with opencode:"
echo "   - Make TUI:    make agent-host"
echo "   - Direct:      make agent"
echo "   - Or continue using the MCP tools directly"
echo ""
