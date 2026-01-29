import os
from venv import logger
import importlib
import sys
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Create FastAPI app
app = FastAPI(title="Monkey Resonance API")

# Allow host/port configuration via environment variables
host = os.environ.get("MCP_HOST", "0.0.0.0")
port = int(os.environ.get("MCP_PORT", "8005"))

logger.info(f"API server will run on {host}:{port}")

# Models for request/response bodies
class EffectParams(BaseModel):
    effect_path: str
    params: dict = None
    position: int = None

class UpdateEffectParams(BaseModel):
    effect_path: str
    params: dict = None
    position: int = None

@app.get("/global_status")
def global_status() -> bool:
    """Let you know if everything is ok and the musical backend is working as intended."""
    main_variables = list(sys.modules["__main__"].__dict__.keys())

    if "AudioStream" not in main_variables:
        logger.error("No AudioStream class in main!")
        return False
    if "audio_devices" not in main_variables:
        logger.error("No audio device were found")
        return False
    return True

@app.get("/list_inputs_outputs")
def list_inputs_outputs() -> tuple[dict[int, dict], dict[int, dict]]:
    """Let you find out which audio devices were found and get some basic informations about the found devices.
    
    First element of the tuple are the inputs, second are the outputs. Integer dict keys are the devices index.
    """
    inputs_outputs = sys.modules["__main__"].__dict__.get("audio_devices")
    if not inputs_outputs:
        logger.error("No input or ouput audio periferic found")
        return ({}, {})
    logger.info(f"Devices found : {inputs_outputs}")
    return inputs_outputs

@app.get("/list_inputs")
def list_inputs() -> list:
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

@app.get("/list_effects/{index}")
def get_input_effects(index: int) -> dict:
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

@app.post("/mute_input/{index}")
def mute_input(index: int) -> dict:
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

    if not hasattr(inp, "stop"):
        logger.error(f"Piste d'entrée en input {index} invalide (pas d'attribut stop)...")
        return {"error": "invalid input"}
    try:
        inp.stop()
        logger.info(f"La pisted d'entrée {index} a été mute")
        return {"success": f"input {index} was succesfully muted!"}
    except Exception as e:
        logger.error(f"Impossible de mute : {str(e)}")
        return {"error": str(e)}

@app.post("/unmute_input/{index}")
def unmute_input(index: int) -> dict:
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

    if not hasattr(inp, "start"):
        logger.error(f"Piste d'entrée en input {index} invalide (pas d'attribut start)...")
        return {"error": "invalid input"}

    try:
        inp.start()
        logger.info(f"La pisted d'entrée {index} a été activée!")
        return {"success": f"input {index} was succesfully unmuted!"}
    except Exception as e:
        return {"error": str(e)}

@app.post("/add_effect_to_input/{index}")
def add_effect_to_input(index: int, params: EffectParams) -> dict:
    """Add an effect to input at index.
    effect_path: module.Class string, e.g. 'pyo.Delay'
    params: dict of kwargs for the effect class
    position: position in chain (None for append)
    """
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
        if not isinstance(params.effect_path, str) or '.' not in params.effect_path:
            return {"error": "effect_path must be 'module.Class' string"}
        module_name, class_name = params.effect_path.rsplit('.', 1)
        module = importlib.import_module(module_name)
        effect_cls = getattr(module, class_name)
        # call add_effect(position, effect_cls, **params)
        inp.add_effect(params.position, effect_cls, **params.params)
        return {"result": "effect_added"}
    except Exception as e:
        return {"error": str(e)}

@app.post("/update_effect/{index}")
def update_effect(index: int, params: UpdateEffectParams) -> dict:
    """Add an effect to input at index.
    effect_path: module.Class string, e.g. 'pyo.Delay'
    params: dict of kwargs for the effect class
    position: position in chain (None for append)
    """
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
        if not isinstance(params.effect_path, str) or '.' not in params.effect_path:
            return {"error": "effect_path must be 'module.Class' string"}
        module_name, class_name = params.effect_path.rsplit('.', 1)
        module = importlib.import_module(module_name)
        effect_cls = getattr(module, class_name)
        # call add_effect(position, effect_cls, **params)
        inp.add_effect(params.position, effect_cls, **params.params)
        return {"result": "effect_added"}
    except Exception as e:
        return {"error": str(e)}

@app.post("/remove_effect_from_input/{index}")
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

@app.post("/start_input_recording/{index}")
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

@app.post("/stop_input_recording/{index}")
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

def start_api():
    import uvicorn
    uvicorn.run(app, host=host, port=port)
