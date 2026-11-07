import asyncio
import logging
import os
import sys

# Ensure venv packages are found before local modules (fixes mcp package vs mcp.py conflict)
sys.path.insert(0, '/opt/venv/lib/python3.12/site-packages')

from mcp.server import MCPServer

try:
    from libs.music_analysis import get_analyzer
    _analyzer_available = True
except ImportError:  # pragma: no cover - dépendances optionnelles
    _analyzer_available = False

from libs.utils import APP_BASE_FOLDER, APP_FOLDERS

logger = logging.getLogger(__name__)

# Temps laissé au ring buffer wet pour se remplir avant une lecture/analyse.
WET_WARMUP_S = 0.4

# Allow host/port configuration via environment variables so the
# MCP's HTTP transport can be exposed (for testing tools/clients).
# Bind host/port for the HTTP transport. Use 0.0.0.0 to make it reachable
# from the host when the container publishes the port.
host = os.environ.get("MCP_HOST", "0.0.0.0")
port = int(os.environ.get("MCP_PORT", "8005"))
# Transport par défaut : HTTP streamable (MCP 2.x). "stdio" reste possible
# pour les clients qui lancent le process eux-mêmes (ex : mcp-stdio.sh).
transport = os.environ.get("MCP_TRANSPORT", "streamable-http")

if transport == "stdio":
    logger.info("MCP server will run over stdio")
else:
    logger.info("MCP server will run on http://%s:%s/mcp", host, port)
# Create the MCP server instance. Host/port are passed to run() with the
# streamable-http transport (MCP 2.x moved them out of the constructor).
mcp = MCPServer("Monkey Resonance MCP")


@mcp.tool()
async def global_status() -> bool:
    """Let you know if everything is ok and the musical backend is working as intended."""
    try:
        main_variables = list(sys.modules["__main__"].__dict__.keys())

        if "AudioStream" not in main_variables:
            logger.error("No AudioStream class in main!")
            return False
        if "audio_devices" not in main_variables:
            logger.error("No audio device were found")
            return False
        return True
    except Exception as e:
        logger.error(f"Error in global_status: {e}")
        return False
@mcp.tool()
async def list_inputs_outputs() -> tuple[dict[int, dict], dict[int, dict]]:
    """Let you find out which audio devices were found and get some basic informations about the found devices.
    
    
    First element of the tuple are the inputs, second are the outputs. Integer dict keys are the devices index.
    """
    try:
        inputs_outputs = sys.modules["__main__"].__dict__.get("audio_devices")
        if not inputs_outputs:
            logger.error("No input or ouput audio periferic found")
            return ({}, {})
        logger.info(f"Devices found : {inputs_outputs}")    
        return inputs_outputs
    except Exception as e:
        logger.error(f"Error in list_inputs_outputs: {e}")
        return ({}, {})

@mcp.prompt()
async def help():
    """A prompt that explain how to use the different tools"""
    return """
    You can use ressources to get informations on the current state of my music server and instruments.
    The tools are here for you to use to answer the users needs. 
    It'll help you handle instruments sounds and effects.


    Make sure you always finish your answers by : 'Have fun monkey!'
     """
@mcp.tool()
async def list_inputs( ) -> list:
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
async def get_input_effects(index: int) -> dict:
    """Return the effects chain for the input at `index` (list of effect descriptors)."""
    logger.info(f"Looking for input {index!s} effects...")
    main = sys.modules.get("__main__")

    inputs = main.__dict__.get("inputs", None)

    try:
        inp = inputs[index]
    except Exception:
        logger.error(f"Can't find any input with index {index!s}...")
        return {"error": "invalid index"}
    try:
        effects_chain = getattr(inp, "effects_chain", [])
        logger.info(f"Effect chain for index {index!s} : {effects_chain}")
        return {"index": index, "effects": effects_chain}
    except Exception as e:
        logger.error(f"Can't get effect chain for input index {index!s}")
        return {"error": str(e)}


#@mcp.tool()
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
async def mute_input(index: int) -> dict:
    """Mute the given input by stopping its output. Returns status or error."""
    logger.info(f"En train de mute input {index!s}")
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
        logger.error(f"Impossible de mute : {e!s}")   
        return {"error": str(e)}     

@mcp.tool()
async def unmute_input(index: int) -> dict:
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
async def add_effect_to_input(index: int, effect_path: str, params: dict | None = None, position: int | None = None) -> dict:
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
        # Le moteur Pedalboard résout lui-même les chemins pyo/pedalboard.
        inp.add_effect(position, effect_path, **params)
        return {"result": "effect_added"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def update_effect(index: int, effect_path: str, params: dict | None = None, position: int | None = None) -> dict:
    """Update the parameters of an effect at `position` in input `index`.

    effect_path: module.Class string, kept for API compatibility
    params: dict of kwargs for the effect class
    position: index of the effect in the chain (required)
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
        if position is None:
            return {"error": "position is required to update an effect"}
        inp.update_effect(position, **params)
        return {"result": "effect_updated"}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
async def remove_effect_from_input(index: int, effect_index: int) -> dict:
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
async def save_input_effects(index: int, name: str) -> dict:
    """Save the effect chain of the input at `index` as `saved_effects/<name>.json`."""
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
        filepath = inp.save_effects(name)
        return {"result": filepath}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def load_input_effects(index: int, name: str) -> dict:
    """Load `saved_effects/<name>.json` into the effect chain of the input at `index`."""
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
        inp.load_effects(name)
        return {"result": "effects_loaded", "effects": inp.effects_chain}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def start_input_recording(
    index: int, filename: str | None = None, wet: bool = False
) -> dict:
    """Start recording on the input at `index`. Returns filepath or error.

    ``wet=True`` enregistre le signal **après les effets** (sortie simulée) :
    la chaîne courante est rejouée sur l'entrée captée par l'analyseur, puis
    écrite dans le WAV. ``wet=False`` (défaut) enregistre l'entrée brute.
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

    if wet:
        if not _analyzer_available:
            return {"error": "Audio analyzer not available"}
        analyzer = get_analyzer()
        if analyzer is None:
            return {"error": "Analyzer not initialized (no audio input)"}
        try:
            analyzer.enable_wet()
            # Laisse le ring buffer wet se remplir avant d'ouvrir le fichier.
            await asyncio.sleep(WET_WARMUP_S)
            filepath = analyzer.start_wet_recording(filename)
            return {"result": filepath, "source": "wet"}
        except Exception as e:
            return {"error": str(e)}

    try:
        filepath = inp.start_recording(filename) if hasattr(inp, 'start_recording') else None
        return {"result": filepath, "source": "dry"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def stop_input_recording(index: int, wet: bool = False) -> dict:
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

    if wet:
        if not _analyzer_available:
            return {"error": "Audio analyzer not available"}
        analyzer = get_analyzer()
        if analyzer is None:
            return {"error": "Analyzer not initialized (no audio input)"}
        try:
            filepath = analyzer.stop_wet_recording()
            return {"result": filepath, "source": "wet"}
        except Exception as e:
            return {"error": str(e)}

    try:
        filepath = inp.stop_recording() if hasattr(inp, 'stop_recording') else None
        return {"result": filepath, "source": "dry"}
    except Exception as e:
        return {"error": str(e)}


# ----------------------------------------------------------------------
# Looper : lecture des enregistrements dans le moteur
# ----------------------------------------------------------------------
def _input_at(index: int):
    """Retourne ``(input, error)`` pour l'index demandé."""
    main = sys.modules.get("__main__")
    if main is None:
        return None, {"error": "__main__ not available"}
    inputs = main.__dict__.get("inputs", None)
    if not inputs:
        return None, {"error": "inputs not found"}
    try:
        return inputs[index], None
    except Exception:
        return None, {"error": "invalid index"}


@mcp.tool()
async def list_recordings() -> list[dict]:
    """Liste les WAV disponibles dans `records/` (nom, durée, taille)."""
    folder = os.path.join(APP_BASE_FOLDER, APP_FOLDERS["RECORDS"])
    result: list[dict] = []
    if not os.path.isdir(folder):
        return result
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(".wav"):
            continue
        path = os.path.join(folder, name)
        try:
            entry = {
                "filename": name,
                "size_mb": round(os.path.getsize(path) / (1024 * 1024), 2),
            }
            try:
                import wave

                with wave.open(path, "rb") as wav:
                    rate = wav.getframerate()
                    entry["duration_s"] = (
                        round(wav.getnframes() / rate, 2) if rate else None
                    )
                    entry["channels"] = wav.getnchannels()
            except (wave.Error, OSError, EOFError):
                entry["duration_s"] = None
            result.append(entry)
        except OSError as exc:
            result.append({"filename": name, "error": str(exc)})
    return result


@mcp.tool()
async def play_recording(
    index: int, filename: str, loop: bool = True, volume: float = 1.0
) -> dict:
    """Joue un WAV de `records/` dans le moteur, mixé avec le jeu live.

    ``loop=True`` rejoue le fichier en boucle jusqu'à `stop_playback`.
    ``volume`` est appliqué à la boucle seule (1.0 = niveau du fichier).
    """
    inp, error = _input_at(index)
    if error is not None:
        return error
    if not hasattr(inp, "play_recording"):
        return {"error": "playback not supported by this engine"}
    try:
        return {"result": "playing", "playback": inp.play_recording(
            filename, loop=loop, volume=volume
        )}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def stop_playback(index: int) -> dict:
    """Arrête la boucle en cours sur l'input `index`."""
    inp, error = _input_at(index)
    if error is not None:
        return error
    if not hasattr(inp, "stop_playback"):
        return {"error": "playback not supported by this engine"}
    try:
        stopped = inp.stop_playback()
        return {
            "result": "stopped" if stopped else "no_playback",
            "playback": stopped,
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def playback_status(index: int) -> dict:
    """État de la lecture en cours (fichier, boucle, position) ou `null`."""
    inp, error = _input_at(index)
    if error is not None:
        return error
    if not hasattr(inp, "playback_status"):
        return {"playback": None}
    try:
        return {"playback": inp.playback_status()}
    except Exception as e:
        return {"error": str(e)}


# ----------------------------------------------------------------------
# Volume / analyse musicale
# ----------------------------------------------------------------------
@mcp.tool()
async def set_output_volume(index: int, volume: float) -> dict:
    """Set the output volume (0.0 = mute, 1.0 = normal).

    ``index`` is kept for API compatibility (0 = left, 1 = right). Pedalboard
    applies a single gain to the stereo stream, so both channels are affected.
    """
    main = sys.modules.get("__main__")
    if main is None:
        return {"error": "__main__ not available"}
    inputs = main.__dict__.get("inputs", None)
    if not inputs:
        return {"error": "inputs not found"}
    try:
        inp = inputs[0]
        channels = int(getattr(inp, "num_output_channels", 2))
        if index < 0 or index >= channels:
            return {"error": f"Output index {index} out of range (0..{channels - 1})"}
        inp.global_volume = max(float(volume), 0.0)
        return {
            "result": f"Volume set to {inp.global_volume} for output {index} (stereo)"
        }
    except Exception as e:
        return {"error": str(e)}


def _analyzer_reply(kind: str, index: int, *, wet: bool = False, **kwargs: object) -> dict:
    """Appelle l'analyseur global et emballe le résultat comme l'ancien MCP."""
    if not _analyzer_available:
        return {"error": "Audio analyzer not available"}
    analyzer = get_analyzer()
    if analyzer is None:
        return {"error": "Analyzer not initialized (no audio input)"}
    try:
        if kind == "profile":
            return {"profile": analyzer.analyze_audio_profile(index, wet=wet)}
        if kind == "rms":
            return {"rms": analyzer.analyze_rms(index, wet=wet, **kwargs)}
        if kind == "pitch":
            return {"pitch": analyzer.analyze_pitch(index, wet=wet)}
        if kind == "frequency":
            return {"frequency": analyzer.analyze_frequency(index, wet=wet, **kwargs)}
        return {"error": f"unknown analysis: {kind}"}
    except Exception as e:
        return {"error": str(e)}


async def _prepare_wet() -> dict | None:
    """Active le signal wet et laisse le ring buffer se remplir."""
    if not _analyzer_available:
        return {"error": "Audio analyzer not available"}
    analyzer = get_analyzer()
    if analyzer is None:
        return {"error": "Analyzer not initialized (no audio input)"}
    analyzer.enable_wet()
    await asyncio.sleep(WET_WARMUP_S)
    return None


@mcp.tool()
async def get_audio_profile(index: int, wet: bool = False) -> dict:
    """Get a comprehensive audio profile (RMS, pitch, MIDI note, spectrum).

    ``wet=True`` analyse le signal **après les effets** (sortie simulée),
    ``wet=False`` l'entrée brute.
    """
    if wet:
        error = await _prepare_wet()
        if error is not None:
            return error
    return _analyzer_reply("profile", index, wet=wet)


@mcp.tool()
async def get_rms_level(index: int, window_size: int = 2048, wet: bool = False) -> dict:
    """Get the RMS / peak level for an input channel (``wet=True``: post-effets)."""
    if wet:
        error = await _prepare_wet()
        if error is not None:
            return error
    return _analyzer_reply("rms", index, wet=wet, window_size=window_size)


@mcp.tool()
async def get_pitch_info(index: int, wet: bool = False) -> dict:
    """Get the detected pitch, MIDI note and confidence (``wet=True``: post-effets)."""
    if wet:
        error = await _prepare_wet()
        if error is not None:
            return error
    return _analyzer_reply("pitch", index, wet=wet)


@mcp.tool()
async def get_frequency_analysis(index: int, fft_size: int = 2048, wet: bool = False) -> dict:
    """Get FFT analysis (dominant frequency, centroid, bands, peaks).

    ``wet=True`` analyse le signal après les effets.
    """
    if wet:
        error = await _prepare_wet()
        if error is not None:
            return error
    return _analyzer_reply("frequency", index, wet=wet, fft_size=fft_size)


def start_mcp():
    """Démarre le serveur MCP.

    Transport par défaut : HTTP streamable, endpoint ``/mcp``
    (``http://<host>:<port>/mcp``). ``MCP_TRANSPORT=stdio`` force le stdio
    pour un client qui lance lui-même le process.
    """
    if transport == "stdio":
        mcp.run(transport="stdio")
        return
    mcp.run(transport="streamable-http", host=host, port=port)

