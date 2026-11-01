#!/usr/bin/env python3
"""
Standalone MCP server runner for Monkey Resonance.
Can be run without devcontainer, directly on host or in production container.

Usage:
    python scripts/run-standalone-mcp.py
"""

import sys
import os

# Add app directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import pyo
from libs.audio_stream import AudioStream

def main():
    """Initialize audio and start MCP server."""
    # Check audio device availability
    if not os.path.exists('/dev/snd'):
        print("ERROR: No audio device available at /dev/snd")
        print("Please ensure audio is shared with the container.")
        sys.exit(1)

    # Initialize pyo server
    print("Initializing pyo server...")
    s = pyo.Server(nchnls=2)
    try:
        s.boot()
        print("pyo server booted successfully")
    except Exception as e:
        print(f"ERROR: Failed to boot pyo server: {e}")
        sys.exit(1)
    
    s.start()
    print("pyo server started")
    
    # Create audio inputs
    input_audio_device = 0
    input_nbchannels = 2
    
    inputs = [pyo.Input(i) for i in range(input_nbchannels)]
    print(f"Created {len(inputs)} audio input(s)")
    
    # Expose variables in __main__ for MCP server to access
    main_module = type(sys)('__main__')
    main_module.AudioStream = AudioStream
    main_module.audio_devices = ([], [])
    main_module.inputs = inputs
    main_module.pyo_server = s
    
    print("\n" + "="*60)
    print("MCP Server starting on http://0.0.0.0:8005")
    print("Press Ctrl+C to stop")
    print("="*60 + "\n")
    
    # Start MCP server with HTTP transport
    from server.server import start_mcp
    start_mcp()

if __name__ == "__main__":
    main()
