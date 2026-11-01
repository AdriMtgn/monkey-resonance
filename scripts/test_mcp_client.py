#!/usr/bin/env python3
"""Test script pour vérifier le MCP client."""

import asyncio
from mcp import Client

async def main():
    print("Connecting to MCP server at http://localhost:8005/mcp...")
    
    async with Client("http://localhost:8005/mcp") as client:
        # List available tools
        print("\n=== Listing Tools ===")
        tools = await client.list_tools()
        for tool in tools.tools:
            print(f"\n🔧 {tool.name}")
            print(f"   Description: {tool.description or 'N/A'}")
            print(f"   Input Schema: {tool.inputSchema}")
        
        # Call a tool - global_status
        print("\n=== Calling global_status() ===")
        result = await client.call_tool("global_status")
        print(f"Content: {result.content}")
        print(f"Structured: {result.structured_content}")
        print(f"Is Error: {result.is_error}")
        
        # Call another tool - list_inputs
        print("\n=== Calling list_inputs() ===")
        result = await client.call_tool("list_inputs")
        print(f"Content: {result.content}")
        print(f"Structured: {result.structured_content}")
        print(f"Is Error: {result.is_error}")

if __name__ == "__main__":
    asyncio.run(main())
