#!/usr/bin/env python3
"""
Standalone MCP server runner for stdio transport (opencode).
This is a simplified version that doesn't require the full FastMCP HTTP server.
"""

import sys
import os

# Add app directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import pyo
from libs.audio_stream import AudioStream

def main():
    """Initialize audio and start MCP server via stdio."""
    # Check audio device availability
    if not os.path.exists('/dev/snd'):
        print("ERROR: No audio device available at /dev/snd", file=sys.stderr)
        sys.exit(1)

    # Initialize pyo server
    print("Initializing pyo server...", file=sys.stderr)
    s = pyo.Server(nchnls=2)
    try:
        s.boot()
        print("pyo server booted successfully", file=sys.stderr)
    except Exception as e:
        print(f"ERROR: Failed to boot pyo server: {e}", file=sys.stderr)
        sys.exit(1)
    
    s.start()
    print("pyo server started", file=sys.stderr)
    
    # Create audio inputs
    input_audio_device = 0
    input_nbchannels = 2
    
    inputs = [pyo.Input(i) for i in range(input_nbchannels)]
    print(f"Created {len(inputs)} audio input(s)", file=sys.stderr)
    
    # Expose variables in __main__ for MCP server to access
    main_module = type(sys)('__main__')
    main_module.AudioStream = AudioStream
    main_module.audio_devices = ([], [])
    main_module.inputs = inputs
    main_module.pyo_server = s
    
    # Now import and run the MCP server with stdio transport
    # We need to reload the server module to get the mcp instance
    if 'server.server' in sys.modules:
        del sys.modules['server.server']
    
    from mcp.server import MCPServer
    
    # Create MCP server with stdio transport
    mcp = MCPServer("Monkey Resonance MCP")
    
    # Define tools that access the main module variables
    @mcp.tool()
    async def global_status() -> bool:
        """Let you know if everything is ok and the musical backend is working as intended."""
        try:
            main_variables = list(sys.modules["__main__"].__dict__.keys())
            if "AudioStream" not in main_variables:
                print("No AudioStream class in main!", file=sys.stderr)
                return False
            if "audio_devices" not in main_variables:
                print("No audio device were found", file=sys.stderr)
                return False
            return True
        except Exception as e:
            print(f"Error in global_status: {e}", file=sys.stderr)
            return False
    
    @mcp.tool()
    async def list_inputs_outputs() -> tuple[dict[int, dict], dict[int, dict]]:
        """List audio devices."""
        try:
            inputs_outputs = sys.modules["__main__"].__dict__.get("audio_devices")
            if not inputs_outputs:
                print("No input or output audio peripheral found", file=sys.stderr)
                return ({}, {})
            print(f"Devices found: {inputs_outputs}", file=sys.stderr)
            return inputs_outputs
        except Exception as e:
            print(f"Error in list_inputs_outputs: {e}", file=sys.stderr)
            return ({}, {})
    
    @mcp.tool()
    async def list_inputs() -> list:
        """Return a list of available AudioStream inputs."""
        main = sys.modules.get("__main__")
        if main is None:
            return []
        inputs = main.__dict__.get("inputs", [])
        result = []
        for i, inp in enumerate(inputs):
            try:
                result.append({
                    "index": i,
                    "repr": str(inp),
                    "recording": bool(getattr(inp, "recording", False)),
                    "effects": getattr(inp, "effects_chain", []),
                })
            except Exception as e:
                result.append({"index": i, "error": str(e)})
        print(f"List of inputs: {result}", file=sys.stderr)
        return result
    
    @mcp.tool()
    async def mute_input(index: int) -> dict:
        """Mute the given input."""
        main = sys.modules.get("__main__")
        inputs = main.__dict__.get("inputs", None)
        if not inputs:
            return {"error": "inputs not found"}
        try:
            inp = inputs[index]
            if not hasattr(inp, "stop"):
                return {"error": "invalid input"}
            inp.stop()
            return {"success": f"input {index} was successfully muted!"}
        except Exception as e:
            return {"error": str(e)}
    
    @mcp.tool()
    def unmute_input(index: int) -> dict:
        """Unmute the given input."""
        main = sys.modules.get("__main__")
        inputs = main.__dict__.get("inputs", None)
        if not inputs:
            return {"error": "inputs not found"}
        try:
            inp = inputs[index]
            if not hasattr(inp, "start"):
                return {"error": "invalid input"}
            inp.start()
            return {"success": f"input {index} was successfully unmuted!"}
        except Exception as e:
            return {"error": str(e)}
    
    # Run MCP server with stdio transport
    print("Starting MCP server via stdio...", file=sys.stderr)
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
