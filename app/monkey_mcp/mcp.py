import os
from venv import logger
from mcp.server.fastmcp import FastMCP, Context
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
@mcp.resource("/global_status")
def global_status(ctx: Context) -> bool:
    """Let you know if everything is ok and the musical backend is working as intended."""
    main_variables = list(sys.modules["__main__"].__dict__.keys())

    if "AudioStream" not in main_variables:
        logger.error("No AudioStream class in main!")
        return False
    if "audio_devices" not in main_variables:
        logger.error("No audio device were found")
        return False
    return True
@mcp.tool()
@mcp.resource("/list_inputs_outputs")
def list_inputs_outputs(ctx: Context) -> tuple[dict[int, dict], dict[int, dict]]:
    """Let you find out which audio devices were found and get some basic informations about the found devices.
    
    
    First element of the tuple are the inputs, second are the outputs. Integer dict keys are the devices index.
    """
    inputs_outputs = sys.modules["__main__"].__dict__.get("audio_devices")
    if not inputs_outputs:
        logger.error("No input or ouput audio periferic found")
        return ({},{})
    logger.info(f"Devices found : {inputs_outputs}")    
    return inputs_outputs

@mcp.prompt()
def help():
    """A prompt that explain how to use the different tools"""
    return """
    You can use ressources to get informations on the current state of my music server and instruments.
    The tools are here for you to use to answer the users needs. 
    It'll help you handle instruments sounds and effects.


    Make sure you always finish your answers by : 'Have fun monkey!'
     """
@mcp.tool()
@mcp.resource("/list_inputs")
def list_inputs(ctx: Context) -> list:
    """Return a list of available AudioStream inputs with basic state (index, repr, recording)."""
    main = sys.modules.get("__main__")
    if main is None:
        return []
    logger.info("Récupération des inputs")
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
    logger.info(f"liste des inputs : {result}")        
    return result

@mcp.tool()
@mcp.resource("/list_effects/{index}")
def get_input_effects(ctx: Context,index: int) -> dict:
    """Return the effects chain for the input at `index` (list of effect descriptors)."""
    logger.info(f"Looking for input {str(index)} effects...")
    main = sys.modules.get("__main__")

    inputs = main.__dict__.get("inputs", None)

    try:
        inp = inputs[index]
    except Exception:
        logger.error(f"Can't find any input with index {str(index)}...")
        return {"error": "invalid index"}
    try:
        effects_chain = getattr(inp, "effects_chain", [])
        logger.info(f"Effect chain for index {str(index)} : {effects_chain}")
        return {"index": index, "effects": effects_chain}
    except Exception as e:
        logger.error(f"Can't get effect chain for input index {str(index)}")
        return {"error": str(e)}


#@mcp.tool()
#@mcp.resource("/list_effects/{index}")
#def get_input_effect_details(ctx: Context,input_index: int, effect_index) -> dict:
#    """Returns details about the current effect applyed toinput index in position effect_index"""
#    logger.info(f"Looking for input {str(index)} effects...")
#    main = sys.modules.get("__main__")
#
#    inputs = main.__dict__.get("inputs", None)
#
#    try:
#        inp = inputs[index]
#    except Exception:
#        logger.error(f"Can't find any input with index {str(index)}...")
#        return {"error": "invalid index"}
#    try:
#        effects_chain = getattr(inp, "effects_chain", [])
#        logger.info(f"Effect chain for index {str(index)} : {effects_chain}")
#        return {"index": index, "effects": effects_chain}
#    except Exception as e:
#        logger.error(f"Can't get effect chain for input index {str(index)}")
#        return {"error": str(e)}
#    try:
#        effect = effect_chain[effect_index] 
#        return vars(effect)   


@mcp.tool()
def mute_input(ctx: Context,index: int) -> dict:
    """Mute the given input by stopping its output. Returns status or error."""
    logger.info(f"En train de mute input {str(index)}")
    main = sys.modules.get("__main__")
    inputs = main.__dict__.get("inputs", None)
    if not inputs:
        logger.error("Impossible de trouver les pistes d'entrée...")
        return {"error": "inputs not found"}
    try:
        inp = inputs[index]
    except Exception:
        logger.error(f"Impossible de trouver une piste d'entrée sur l'index {index}")
        return {"error": "invalid index"}

    if not hasattr(inp,"stop"):
        logger.error(f"Piste d'entrée en input {index} invalide (pas d'attribut stop)...") 
        return {"error": "invalid input"}   
    try:
        inp.stop()
        logger.info(f"La pisted d'entrée {index} a été mute")
        return {"success" : f"input {index} was succesfully muted!"}
    except Exception as e:
        logger.error(f"Impossible de mute : {str(e)}")   
        return {"error": str(e)}     

@mcp.tool()
def unmute_input(ctx: Context, index: int) -> dict:
    """Unmute the given input by starting its output. Returns status or error."""
    main = sys.modules.get("__main__")
    inputs = main.__dict__.get("inputs", None)
    if not inputs:
        logger.error("Impossible de trouver les pistes d'entrée...")
        return {"error": "inputs not found"}
    try:
        inp = inputs[index]
    except Exception:
        logger.error(f"Impossible de trouver une piste d'entrée sur l'index {index}")
        return {"error": "invalid index"}

    if not hasattr(inp,"start"):
        logger.error(f"Piste d'entrée en input {index} invalide (pas d'attribut start)...") 
        return {"error": "invalid input"}

    try:
        inp.start()
        logger.info(f"La pisted d'entrée {index} a été activée!")
        return {"success" : f"input {index} was succesfully unmuted!"}
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
def update_effect(index: int, effect_path: str, params: dict = None, position: int = None) -> dict:
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

