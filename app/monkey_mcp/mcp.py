import os
from venv import logger
from mcp.server.fastmcp import FastMCP
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

@mcp.tool()
def call_method_on_global(obj_name: str, method: str, args: list = None, kwargs: dict = None) -> dict:
    """Call a method on a global object by name."""
    args = args or []
    kwargs = kwargs or {}
    obj = sys.modules["__main__"].__dict__.get(obj_name)
    if not obj:
        return {"error": "object not found"}
    func = getattr(obj, method, None)
    if not func or not callable(func):
        return {"error": "method not found"}
    try:
        result = func(*args, **kwargs)
        return {"result": str(result)}
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

