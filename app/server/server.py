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

from libs.midi_control import list_midi_devices as midi_devices_list
from libs.mixer import mixer_from_main
from libs.performance import MidiEvent
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
                "name": getattr(inp, "name", f"input_{i}"),
                "channels": list(getattr(inp, "input_channels", ())),
                "repr": str(inp),
                "recording": bool(getattr(inp, "recording", False)),
                "volume": round(float(getattr(inp, "global_volume", 1.0)), 4),
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
# Performance : presets, bypass, looper et mappings MIDI
# ----------------------------------------------------------------------
def _performance_controller():
    """Retourne ``(contrôleur, erreur)`` depuis ``__main__``."""
    main = sys.modules.get("__main__")
    if main is None:
        return None, {"error": "__main__ not available"}
    controller = main.__dict__.get("performance")
    if controller is None:
        return None, {"error": "performance controller not initialized"}
    return controller, None


@mcp.tool()
async def list_presets() -> dict:
    """Liste les presets d'effets disponibles et le preset courant."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    return {
        "presets": controller.list_presets(),
        "order": controller.preset_order(),
        "current": controller.current_preset,
    }


@mcp.tool()
async def load_preset(name: str) -> dict:
    """Charge un preset d'effets par son nom (fichier ``saved_effects/<name>.json``)."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    try:
        return controller.apply_preset(name)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def next_preset() -> dict:
    """Charge le preset suivant dans l'ordre de performance configuré."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    try:
        return controller.next_preset()
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def previous_preset() -> dict:
    """Charge le preset précédent dans l'ordre de performance configuré."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    try:
        return controller.previous_preset()
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def performance_status() -> dict:
    """État complet : preset, mapping MIDI, dernier événement, looper."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    try:
        return controller.status()
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def toggle_effect(
    target: str | int,
    input_index: int | None = None,
) -> dict:
    """Active ou bypass un effet ciblé (position ou chemin ``pedalboard.*``)."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    try:
        return controller.toggle_effect(target, input_index=input_index)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def set_effect_enabled(
    target: str | int,
    enabled: bool,
    input_index: int | None = None,
) -> dict:
    """Force l'état actif/bypass d'un effet ciblé."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    try:
        return controller.set_effect_enabled(
            target,
            enabled,
            input_index=input_index,
        )
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def loop_toggle(input_index: int | None = None) -> dict:
    """Un seul pad : enregistrer, puis lire en boucle, puis arrêter."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    try:
        return controller.loop_toggle(input_index=input_index)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def loop_record(input_index: int | None = None) -> dict:
    """Démarre un enregistrement de boucle sur la piste ciblée."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    try:
        return controller.loop_record(input_index=input_index)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def loop_play(input_index: int | None = None) -> dict:
    """Joue le dernier enregistrement connu en boucle."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    try:
        return controller.loop_play(input_index=input_index)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def loop_stop(input_index: int | None = None) -> dict:
    """Arrête la boucle en cours."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    try:
        return controller.loop_stop(input_index=input_index)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def list_midi_devices() -> dict:
    """Liste les devices raw MIDI visibles dans le container."""
    return {"devices": midi_devices_list()}


@mcp.tool()
async def get_midi_status() -> dict:
    """État de la connexion MIDI, dernier message et mode apprentissage."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    return {
        "midi": controller.midi_status(),
        "last_event": controller.last_event(),
        "last_action": controller.last_action(),
        "learn": controller.learn_status(),
    }


@mcp.tool()
async def list_midi_maps() -> dict:
    """Liste les profils de mapping sauvegardés."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    return {"maps": controller.list_mappings()}


@mcp.tool()
async def get_midi_map() -> dict:
    """Retourne le mapping MIDI actif."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    return {"mapping": controller.get_mapping_dict()}


@mcp.tool()
async def configure_midi_map(changes: dict) -> dict:
    """Met à jour les métadonnées du mapping actif.

    Exemple : ``{"order": ["clean", "space"], "startup_preset": "clean",
    "input_index": 0, "device": "AudioBox", "channel": 0}``. Les clés absentes
    restent inchangées ; les bindings peuvent aussi être remplacés via
    ``{"bindings": [...]}``.
    """
    controller, error = _performance_controller()
    if error is not None:
        return error
    try:
        return controller.configure_mapping(changes)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def save_midi_map(name: str) -> dict:
    """Sauvegarde le mapping actif dans ``saved_midi_maps/<name>.json``."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    try:
        return controller.save_mapping(name)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def load_midi_map(name: str) -> dict:
    """Charge un profil de mapping sauvegardé."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    try:
        return controller.load_mapping(name)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def add_midi_binding(
    source: dict,
    action: dict,
    binding_id: str | None = None,
) -> dict:
    """Ajoute une association MIDI -> action.

    ``source`` : ``{"type": "control_change", "controller": 21, "mode": "press"}``.
    ``action`` : ``{"type": "next_preset"}``, ``{"type": "preset",
    "target": "bass_mid_growl"}``, ``{"type": "toggle_effect", "target":
    "pedalboard.Delay"}``, ``{"type": "loop_toggle"}``, etc.
    """
    controller, error = _performance_controller()
    if error is not None:
        return error
    try:
        return controller.add_binding(source, action, binding_id=binding_id)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def update_midi_binding(
    binding_id: str,
    source: dict | None = None,
    action: dict | None = None,
) -> dict:
    """Modifie la source ou l'action d'une association existante."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    try:
        return controller.update_binding(binding_id, source=source, action=action)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def remove_midi_binding(binding_id: str) -> dict:
    """Supprime une association MIDI."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    try:
        return controller.remove_binding(binding_id)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def simulate_midi_event(event: dict) -> dict:
    """Injecte un événement MIDI pour tester le mapping sans matériel.

    Exemple : ``{"type": "control_change", "channel": 0, "controller": 21,
    "value": 127}``.
    """
    controller, error = _performance_controller()
    if error is not None:
        return error
    try:
        return controller.dispatch_event(MidiEvent.from_dict(event))
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def start_midi_learn() -> dict:
    """Démarre l'apprentissage : le prochain message MIDI est capturé sans être exécuté."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    return controller.start_learn()


@mcp.tool()
async def stop_midi_learn() -> dict:
    """Arrête l'apprentissage et retourne le message capturé."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    return controller.stop_learn()


@mcp.tool()
async def get_midi_learn() -> dict:
    """État du mode apprentissage MIDI."""
    controller, error = _performance_controller()
    if error is not None:
        return error
    return controller.learn_status()


# ----------------------------------------------------------------------
# Volume / analyse musicale
# ----------------------------------------------------------------------
@mcp.tool()
async def set_output_volume(index: int, volume: float) -> dict:
    """Set the volume of an output bus (0.0 = mute, 1.0 = normal).

    ``index`` is the logical output bus index (``get_mixer`` lists them).
    """
    engine, error = mixer_from_main()
    if error is not None:
        return error
    try:
        return {"result": "output_volume_set", **engine.set_output_volume(index, volume)}
    except Exception as e:
        return {"error": str(e)}


# ----------------------------------------------------------------------
# Mixer global : inputs indépendants + bus de sortie
# ----------------------------------------------------------------------
@mcp.tool()
async def get_mixer() -> dict:
    """État complet du mixer : pistes, bus, volumes, balance et routage.

    ``inputs[i].routes`` donne le volume d'envoi de la piste ``i`` vers chaque
    bus de sortie. ``outputs[j]`` décrit le bus ``j`` et ses canaux physiques.
    """
    engine, error = mixer_from_main()
    if error is not None:
        return error
    try:
        return {"mixer": engine.get_mixer_state()}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def add_input(name: str, channels: list[int]) -> dict:
    """Crée une piste indépendante sur les canaux de capture donnés.

    ``channels`` contient 1 ou 2 index de canaux captés (0 = premier canal).
    La piste est routée par défaut vers le bus 0 à 1.0, et vers les autres
    bus à 0.0.
    """
    engine, error = mixer_from_main()
    if error is not None:
        return error
    try:
        return {"result": "input_added", **engine.add_input(name, channels)}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def remove_input(index: int) -> dict:
    """Retire la piste ``index`` du mixer (les index suivants se décalent)."""
    engine, error = mixer_from_main()
    if error is not None:
        return error
    try:
        return engine.remove_input(index)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def set_input_channels(index: int, channels: list[int]) -> dict:
    """Change les canaux de capture traités par la piste ``index``."""
    engine, error = mixer_from_main()
    if error is not None:
        return error
    try:
        return {"result": "input_channels_set", **engine.set_input_channels(index, channels)}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def set_input_mix(
    index: int,
    volume: float | None = None,
    balance: float | None = None,
    left_gain: float | None = None,
    right_gain: float | None = None,
) -> dict:
    """Règle le fader, la balance et les gains gauche/droite d'une piste.

    ``balance`` va de -1 (gauche) à +1 (droite), 0 = centre. ``left_gain`` et
    ``right_gain`` sont des gains linéaires (1.0 = neutre). ``volume`` est le
    fader global de la piste. Les paramètres omis restent inchangés.
    """
    engine, error = mixer_from_main()
    if error is not None:
        return error
    try:
        return engine.set_input_mix(
            index,
            volume=volume,
            balance=balance,
            left_gain=left_gain,
            right_gain=right_gain,
        )
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def set_route(input_index: int, output_index: int, volume: float) -> dict:
    """Règle le volume d'envoi de la piste ``input_index`` vers le bus ``output_index``."""
    engine, error = mixer_from_main()
    if error is not None:
        return error
    try:
        return {"result": "route_set", **engine.set_route(input_index, output_index, volume)}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def add_output(name: str, left_channel: int, right_channel: int | None = None) -> dict:
    """Crée un bus de sortie stéréo mappé sur les canaux physiques donnés.

    Si ``right_channel`` est omis, le bus est mono (gauche = droite).
    """
    engine, error = mixer_from_main()
    if error is not None:
        return error
    try:
        return {"result": "output_added", **engine.add_output(name, left_channel, right_channel)}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def remove_output(index: int) -> dict:
    """Retire le bus de sortie ``index`` (les index suivants se décalent)."""
    engine, error = mixer_from_main()
    if error is not None:
        return error
    try:
        return engine.remove_output(index)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def set_output_channels(index: int, left_channel: int, right_channel: int | None = None) -> dict:
    """Change le mapping physique d'un bus de sortie."""
    engine, error = mixer_from_main()
    if error is not None:
        return error
    try:
        return {
            "result": "output_channels_set",
            **engine.set_output_channels(index, left_channel, right_channel),
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def mute_output(index: int) -> dict:
    """Mute un bus de sortie."""
    engine, error = mixer_from_main()
    if error is not None:
        return error
    try:
        return engine.mute_output(index)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def unmute_output(index: int) -> dict:
    """Unmute un bus de sortie."""
    engine, error = mixer_from_main()
    if error is not None:
        return error
    try:
        return engine.unmute_output(index)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def set_master_volume(volume: float) -> dict:
    """Règle le volume master global (après le mix des bus)."""
    engine, error = mixer_from_main()
    if error is not None:
        return error
    try:
        return {"result": "master_volume_set", **engine.set_master_volume(volume)}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def mute_master() -> dict:
    """Mute la sortie globale (master), sans toucher aux pistes."""
    engine, error = mixer_from_main()
    if error is not None:
        return error
    try:
        engine.mute()
        return {"result": "master_muted"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def unmute_master() -> dict:
    """Unmute la sortie globale (master)."""
    engine, error = mixer_from_main()
    if error is not None:
        return error
    try:
        engine.unmute()
        return {"result": "master_unmuted"}
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

