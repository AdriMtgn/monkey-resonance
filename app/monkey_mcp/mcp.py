import os
from venv import logger
from mcp.server.fastmcp import FastMCP
import importlib
import sys


# Allow host/port configuration via environment variables so the
# MCP's HTTP transport can be exposed (for testing tools/clients).
# Bind host/port for the HTTP transport. Use 0.0.0.0 to make it reachable
# from the host when the container publishes the port.
host = os.environ.get("MCP_HOST", "0.0.0.0")
port = int(os.environ.get("MCP_PORT", "8005"))

logger.info(f"MCP server will run on {host}:{port}")
# Create the MCP server instance
mcp = FastMCP("Monkey Resonance MCP",host=host,port=port)

@mcp.tool()
def list_globals() -> list:
    """List all global variables in the main session."""
    return list(sys.modules["__main__"].__dict__.keys())

# Deprecated: call_method_on_global removed in favor of explicit, safer tools


@mcp.tool()
def list_inputs() -> list:
    """Return a list of available AudioStream inputs with basic state (index, repr, recording)."""
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
    return result


@mcp.tool()
def get_input_effects(index: int) -> dict:
    """Return the effects chain for the input at `index` (list of effect descriptors)."""
    main = sys.modules.get("__main__")
    if main is None:
        return {"error": "__main__ not available"}
    inputs = main.__dict__.get("inputs", None)
    if inputs is None:
        return {"error": "inputs not found"}
    try:
        inp = inputs[index]
    except Exception:
        return {"error": "invalid index"}
    try:
        return {"index": index, "effects": getattr(inp, "effects_chain", [])}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def mute_input(index: int) -> dict:
    """Mute the given input by stopping its output. Returns status or error."""
    main = sys.modules.get("__main__")
    if main is None:
        return {"error": "__main__ not available"}
    inputs = main.__dict__.get("inputs", None)
    if not inputs:
        return {"error": "inputs not found"}
    try:
        inp = inputs[index]
    except Exception:
        return {"error": "invalid index"}
    try:
        if hasattr(inp, 'stop'):
            inp.stop()
            return {"result": "muted"}
        # fallback: set volume to 0 if available
        if hasattr(inp, 'global_volume'):
            inp.global_volume = 0
            if hasattr(inp, '_set_output'):
                inp._set_output()
            return {"result": "muted_via_volume"}
        return {"error": "cannot mute input"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def unmute_input(index: int) -> dict:
    """Unmute the given input by starting its output. Returns status or error."""
    main = sys.modules.get("__main__")
    if main is None:
        return {"error": "__main__ not available"}
    inputs = main.__dict__.get("inputs", None)
    if not inputs:
        return {"error": "inputs not found"}
    try:
        inp = inputs[index]
    except Exception:
        return {"error": "invalid index"}
    try:
        if hasattr(inp, 'start'):
            inp.start()
            return {"result": "unmuted"}
        # fallback: restore volume to 1.0 if available
        if hasattr(inp, 'global_volume'):
            inp.global_volume = 1.0
            if hasattr(inp, '_set_output'):
                inp._set_output()
            return {"result": "unmuted_via_volume"}
        return {"error": "cannot unmute input"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def add_effect_to_input(index: int, effect_path: str, params: dict = None, position: int = None) -> dict:
    """Add an effect to input at index.
    effect_path: module.Class string, e.g. 'pyo.Delay'
    params: dict of kwargs for the effect class
    position: position in chain (None for append)
    """
    params = params or {}
    main = sys.modules.get("__main__")
    if main is None:
        return {"error": "__main__ not available"}
    inputs = main.__dict__.get("inputs", None)
    if inputs is None:
        return {"error": "inputs not found"}
    try:
        inp = inputs[index]
    except Exception:
        return {"error": "invalid index"}
    try:
        if not isinstance(effect_path, str) or '.' not in effect_path:
            return {"error": "effect_path must be 'module.Class' string"}
        module_name, class_name = effect_path.rsplit('.', 1)
        module = importlib.import_module(module_name)
        effect_cls = getattr(module, class_name)
        # call add_effect(position, effect_cls, **params)
        inp.add_effect(position, effect_cls, **params)
        return {"result": "effect_added"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def remove_effect_from_input(index: int, effect_index: int) -> dict:
    """Remove effect by index from input's effect chain."""
    main = sys.modules.get("__main__")
    if main is None:
        return {"error": "__main__ not available"}
    inputs = main.__dict__.get("inputs", None)
    if inputs is None:
        return {"error": "inputs not found"}
    try:
        inp = inputs[index]
    except Exception:
        return {"error": "invalid index"}
    try:
        inp.remove_effect(effect_index)
        return {"result": "effect_removed"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def start_input_recording(index: int, filename: str = None) -> dict:
    """Start recording on the input at `index`. Returns filepath or error."""
    main = sys.modules.get("__main__")
    if main is None:
        return {"error": "__main__ not available"}
    inputs = main.__dict__.get("inputs", None)
    if inputs is None:
        return {"error": "inputs not found"}
    try:
        inp = inputs[index]
    except Exception:
        return {"error": "invalid index"}
    try:
        filepath = inp.start_recording(filename) if hasattr(inp, 'start_recording') else None
        return {"result": filepath}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def stop_input_recording(index: int) -> dict:
    """Stop recording on the input at `index`. Returns filepath or error."""
    main = sys.modules.get("__main__")
    if main is None:
        return {"error": "__main__ not available"}
    inputs = main.__dict__.get("inputs", None)
    if inputs is None:
        return {"error": "inputs not found"}
    try:
        inp = inputs[index]
    except Exception:
        return {"error": "invalid index"}
    try:
        filepath = inp.stop_recording() if hasattr(inp, 'stop_recording') else None
        return {"result": filepath}
    except Exception as e:
        return {"error": str(e)}

def start_mcp():
    # Run the MCP server using the streamable-http transport bound to
    # the configured host and port.
    # Current FastMCP.run (installed in the image) exposes a signature
    # like run(transport, mount_path=None). For streamable-http the
    # library will bind an HTTP server under a mount path. We'll set
    # mount_path to '/' and rely on publishing the container port to
    # make the transport reachable from outside the container. If the
    # installed FastMCP supports different signatures, attempt the more
    # expressive call first and fall back to mount_path only.
    mount_path = os.environ.get("MCP_MOUNT_PATH", "/")


    # Attempt multiple FastMCP.run signatures to be tolerant of installed
    # mcp versions. When the transport needs host binding we prefer the
    # explicit host/port form; otherwise fall back to mount_path-only.
    mcp.run(transport="streamable-http", mount_path=mount_path)

