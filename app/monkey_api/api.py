import logging
import os
import sys

from fastapi import FastAPI
from libs.midi_control import list_midi_devices
from libs.mixer import mixer_from_main
from libs.performance import MidiEvent
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="Monkey Resonance API")

# Allow host/port configuration via environment variables
host = os.environ.get("MCP_HOST", "0.0.0.0")
port = int(os.environ.get("MCP_PORT", "8005"))

logger.info(f"API server will run on {host}:{port}")

# Models for request/response bodies
class EffectParams(BaseModel):
    effect_path: str
    params: dict | None = None
    position: int | None = None

class UpdateEffectParams(BaseModel):
    effect_path: str
    params: dict | None = None
    position: int | None = None

class AddInputParams(BaseModel):
    name: str
    channels: list[int]

class SetInputChannelsParams(BaseModel):
    channels: list[int]

class SetInputMixParams(BaseModel):
    volume: float | None = None
    balance: float | None = None
    left_gain: float | None = None
    right_gain: float | None = None

class SetRouteParams(BaseModel):
    input_index: int
    output_index: int
    volume: float

class AddOutputParams(BaseModel):
    name: str
    left_channel: int
    right_channel: int | None = None

class SetOutputChannelsParams(BaseModel):
    left_channel: int
    right_channel: int | None = None

class VolumeParams(BaseModel):
    volume: float

class EffectTargetParams(BaseModel):
    target: str | int
    input_index: int | None = None

class EffectEnabledParams(EffectTargetParams):
    enabled: bool

class MidiBindingParams(BaseModel):
    source: dict
    action: dict
    id: str | None = None

class UpdateMidiBindingParams(BaseModel):
    source: dict | None = None
    action: dict | None = None

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

@app.post("/mute_input/{index}")
def mute_input(index: int) -> dict:
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

    if not hasattr(inp, "stop"):
        logger.error(f"Piste d'entrée en input {index} invalide (pas d'attribut stop)...")
        return {"error": "invalid input"}
    try:
        inp.stop()
        logger.info(f"La pisted d'entrée {index} a été mute")
        return {"success": f"input {index} was succesfully muted!"}
    except Exception as e:
        logger.error(f"Impossible de mute : {e!s}")
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
        # Le moteur Pedalboard résout lui-même les chemins pyo/pedalboard.
        inp.add_effect(params.position, params.effect_path, **(params.params or {}))
        return {"result": "effect_added"}
    except Exception as e:
        return {"error": str(e)}

@app.post("/update_effect/{index}")
def update_effect(index: int, params: UpdateEffectParams) -> dict:
    """Update the parameters of an effect at `position` in input `index`.

    effect_path: module.Class string, kept for API compatibility
    params: dict of kwargs for the effect class
    position: index of the effect in the chain (required)
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
        if params.position is None:
            return {"error": "position is required to update an effect"}
        inp.update_effect(params.position, **(params.params or {}))
        return {"result": "effect_updated"}
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
def start_input_recording(index: int, filename: str | None = None) -> dict:
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

# ----------------------------------------------------------------------
# Performance : presets, bypass, looper et mappings MIDI
# ----------------------------------------------------------------------
def _performance():
    """Retourne le contrôleur de performance global ou une erreur JSON."""
    main = sys.modules.get("__main__")
    if main is None:
        return None, {"error": "__main__ not available"}
    controller = main.__dict__.get("performance")
    if controller is None:
        return None, {"error": "performance controller not initialized"}
    return controller, None


@app.get("/presets")
def list_presets() -> dict:
    """Liste les presets d'effets et le preset courant."""
    controller, error = _performance()
    if error is not None:
        return error
    return {
        "presets": controller.list_presets(),
        "order": controller.preset_order(),
        "current": controller.current_preset,
    }


@app.get("/presets/current")
def get_current_preset() -> dict:
    """Retourne le preset actuellement chargé."""
    controller, error = _performance()
    if error is not None:
        return error
    return {"preset": controller.current_preset}


@app.post("/presets/next")
def next_preset() -> dict:
    """Charge le preset suivant dans l'ordre configuré."""
    controller, error = _performance()
    if error is not None:
        return error
    try:
        return controller.next_preset()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/presets/previous")
def previous_preset() -> dict:
    """Charge le preset précédent dans l'ordre configuré."""
    controller, error = _performance()
    if error is not None:
        return error
    try:
        return controller.previous_preset()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/presets/{name}")
def load_preset(name: str) -> dict:
    """Charge un preset d'effets par son nom."""
    controller, error = _performance()
    if error is not None:
        return error
    try:
        return controller.apply_preset(name)
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/performance")
def performance_status() -> dict:
    """État complet : preset, mapping MIDI, dernier événement, looper."""
    controller, error = _performance()
    if error is not None:
        return error
    try:
        return controller.status()
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/effects/{input_index}/toggle")
def toggle_effect(input_index: int, params: EffectTargetParams) -> dict:
    """Active ou bypass l'effet ciblé (position ou chemin) sur une piste."""
    controller, error = _performance()
    if error is not None:
        return error
    try:
        return controller.toggle_effect(
            params.target,
            input_index=input_index,
        )
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/effects/{input_index}/enabled")
def set_effect_enabled(input_index: int, params: EffectEnabledParams) -> dict:
    """Force l'état actif/bypass d'un effet."""
    controller, error = _performance()
    if error is not None:
        return error
    try:
        return controller.set_effect_enabled(
            params.target,
            params.enabled,
            input_index=input_index,
        )
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/looper/{input_index}/toggle")
def loop_toggle(input_index: int) -> dict:
    """Un seul pad : enregistrer, lire, arrêter."""
    controller, error = _performance()
    if error is not None:
        return error
    try:
        return controller.loop_toggle(input_index=input_index)
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/looper/{input_index}/record")
def loop_record(input_index: int) -> dict:
    """Démarre un enregistrement de boucle."""
    controller, error = _performance()
    if error is not None:
        return error
    try:
        return controller.loop_record(input_index=input_index)
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/looper/{input_index}/play")
def loop_play(input_index: int) -> dict:
    """Joue le dernier enregistrement connu."""
    controller, error = _performance()
    if error is not None:
        return error
    try:
        return controller.loop_play(input_index=input_index)
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/looper/{input_index}/stop")
def loop_stop(input_index: int) -> dict:
    """Arrête la boucle en cours."""
    controller, error = _performance()
    if error is not None:
        return error
    try:
        return controller.loop_stop(input_index=input_index)
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/midi/devices")
def midi_devices() -> dict:
    """Liste les devices raw MIDI visibles dans le container."""
    return {"devices": list_midi_devices()}


@app.get("/midi/status")
def midi_status() -> dict:
    """État de la connexion MIDI et dernier événement reçu."""
    controller, error = _performance()
    if error is not None:
        return error
    return {
        "midi": controller.midi_status(),
        "last_event": controller.last_event(),
        "last_action": controller.last_action(),
        "learn": controller.learn_status(),
    }


@app.get("/midi/maps")
def list_midi_maps() -> dict:
    """Liste les profils de mapping sauvegardés."""
    controller, error = _performance()
    if error is not None:
        return error
    return {"maps": controller.list_mappings()}


@app.get("/midi/map")
def get_midi_map() -> dict:
    """Retourne le mapping actif."""
    controller, error = _performance()
    if error is not None:
        return error
    return {"mapping": controller.get_mapping_dict()}


@app.patch("/midi/map")
def update_midi_map(changes: dict) -> dict:
    """Met à jour les métadonnées du mapping actif (ordre, device, etc.)."""
    controller, error = _performance()
    if error is not None:
        return error
    try:
        return controller.configure_mapping(changes)
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/midi/maps/{name}/save")
def save_midi_map(name: str) -> dict:
    """Sauvegarde le mapping actif dans ``saved_midi_maps/<name>.json``."""
    controller, error = _performance()
    if error is not None:
        return error
    try:
        return controller.save_mapping(name)
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/midi/maps/{name}/load")
def load_midi_map(name: str) -> dict:
    """Charge un profil de mapping sauvegardé."""
    controller, error = _performance()
    if error is not None:
        return error
    try:
        return controller.load_mapping(name)
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/midi/bindings")
def add_midi_binding(params: MidiBindingParams) -> dict:
    """Ajoute une association source MIDI -> action."""
    controller, error = _performance()
    if error is not None:
        return error
    try:
        return controller.add_binding(
            params.source,
            params.action,
            binding_id=params.id,
        )
    except Exception as exc:
        return {"error": str(exc)}


@app.patch("/midi/bindings/{binding_id}")
def update_midi_binding(binding_id: str, params: UpdateMidiBindingParams) -> dict:
    """Modifie une association existante."""
    controller, error = _performance()
    if error is not None:
        return error
    try:
        return controller.update_binding(
            binding_id,
            source=params.source,
            action=params.action,
        )
    except Exception as exc:
        return {"error": str(exc)}


@app.delete("/midi/bindings/{binding_id}")
def remove_midi_binding(binding_id: str) -> dict:
    """Supprime une association MIDI."""
    controller, error = _performance()
    if error is not None:
        return error
    try:
        return controller.remove_binding(binding_id)
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/midi/simulate")
def simulate_midi_event(event: dict) -> dict:
    """Injecte un événement MIDI pour tester le mapping sans matériel."""
    controller, error = _performance()
    if error is not None:
        return error
    try:
        return controller.dispatch_event(MidiEvent.from_dict(event))
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/midi/learn/start")
def start_midi_learn() -> dict:
    """Démarre le mode apprentissage : le prochain message n'est pas exécuté."""
    controller, error = _performance()
    if error is not None:
        return error
    return controller.start_learn()


@app.post("/midi/learn/stop")
def stop_midi_learn() -> dict:
    """Arrête le mode apprentissage et retourne le dernier message capturé."""
    controller, error = _performance()
    if error is not None:
        return error
    return controller.stop_learn()


@app.get("/midi/learn")
def get_midi_learn() -> dict:
    """État du mode apprentissage."""
    controller, error = _performance()
    if error is not None:
        return error
    return controller.learn_status()


# ----------------------------------------------------------------------
# Mixer global : inputs indépendants + bus de sortie
# ----------------------------------------------------------------------
def _mixer():
    engine, error = mixer_from_main()
    if error is not None:
        return None, error
    return engine, None

@app.get("/mixer")
def get_mixer() -> dict:
    """État complet du mixer (pistes, bus, volumes, balance, routage)."""
    engine, error = _mixer()
    if error is not None:
        return error
    try:
        return {"mixer": engine.get_mixer_state()}
    except Exception as e:
        return {"error": str(e)}

@app.post("/mixer/inputs")
def add_input(params: AddInputParams) -> dict:
    """Crée une piste indépendante sur les canaux de capture donnés."""
    engine, error = _mixer()
    if error is not None:
        return error
    try:
        return {"result": "input_added", **engine.add_input(params.name, params.channels)}
    except Exception as e:
        return {"error": str(e)}

@app.delete("/mixer/inputs/{index}")
def remove_input(index: int) -> dict:
    """Retire une piste du mixer."""
    engine, error = _mixer()
    if error is not None:
        return error
    try:
        return engine.remove_input(index)
    except Exception as e:
        return {"error": str(e)}

@app.patch("/mixer/inputs/{index}/channels")
def set_input_channels(index: int, params: SetInputChannelsParams) -> dict:
    """Change les canaux de capture traités par une piste."""
    engine, error = _mixer()
    if error is not None:
        return error
    try:
        return {"result": "input_channels_set", **engine.set_input_channels(index, params.channels)}
    except Exception as e:
        return {"error": str(e)}

@app.patch("/mixer/inputs/{index}/mix")
def set_input_mix(index: int, params: SetInputMixParams) -> dict:
    """Règle fader, balance et gains gauche/droite d'une piste."""
    engine, error = _mixer()
    if error is not None:
        return error
    try:
        return engine.set_input_mix(
            index,
            volume=params.volume,
            balance=params.balance,
            left_gain=params.left_gain,
            right_gain=params.right_gain,
        )
    except Exception as e:
        return {"error": str(e)}

@app.patch("/mixer/routes")
def set_route(params: SetRouteParams) -> dict:
    """Règle le volume d'envoi d'une piste vers un bus de sortie."""
    engine, error = _mixer()
    if error is not None:
        return error
    try:
        return {
            "result": "route_set",
            **engine.set_route(params.input_index, params.output_index, params.volume),
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/mixer/outputs")
def add_output(params: AddOutputParams) -> dict:
    """Crée un bus de sortie stéréo mappé sur des canaux physiques."""
    engine, error = _mixer()
    if error is not None:
        return error
    try:
        return {
            "result": "output_added",
            **engine.add_output(params.name, params.left_channel, params.right_channel),
        }
    except Exception as e:
        return {"error": str(e)}

@app.delete("/mixer/outputs/{index}")
def remove_output(index: int) -> dict:
    """Retire un bus de sortie."""
    engine, error = _mixer()
    if error is not None:
        return error
    try:
        return engine.remove_output(index)
    except Exception as e:
        return {"error": str(e)}

@app.patch("/mixer/outputs/{index}/channels")
def set_output_channels(index: int, params: SetOutputChannelsParams) -> dict:
    """Change le mapping physique d'un bus de sortie."""
    engine, error = _mixer()
    if error is not None:
        return error
    try:
        return {
            "result": "output_channels_set",
            **engine.set_output_channels(index, params.left_channel, params.right_channel),
        }
    except Exception as e:
        return {"error": str(e)}

@app.patch("/mixer/outputs/{index}/volume")
def set_output_volume(index: int, params: VolumeParams) -> dict:
    """Règle le volume d'un bus de sortie."""
    engine, error = _mixer()
    if error is not None:
        return error
    try:
        return {"result": "output_volume_set", **engine.set_output_volume(index, params.volume)}
    except Exception as e:
        return {"error": str(e)}

@app.post("/mixer/outputs/{index}/mute")
def mute_output(index: int) -> dict:
    """Mute un bus de sortie."""
    engine, error = _mixer()
    if error is not None:
        return error
    try:
        return engine.mute_output(index)
    except Exception as e:
        return {"error": str(e)}

@app.post("/mixer/outputs/{index}/unmute")
def unmute_output(index: int) -> dict:
    """Unmute un bus de sortie."""
    engine, error = _mixer()
    if error is not None:
        return error
    try:
        return engine.unmute_output(index)
    except Exception as e:
        return {"error": str(e)}

@app.patch("/mixer/master")
def set_master_volume(params: VolumeParams) -> dict:
    """Règle le volume master global."""
    engine, error = _mixer()
    if error is not None:
        return error
    try:
        return {"result": "master_volume_set", **engine.set_master_volume(params.volume)}
    except Exception as e:
        return {"error": str(e)}

@app.post("/mixer/master/mute")
def mute_master() -> dict:
    """Mute la sortie globale."""
    engine, error = _mixer()
    if error is not None:
        return error
    try:
        engine.mute()
        return {"result": "master_muted"}
    except Exception as e:
        return {"error": str(e)}

@app.post("/mixer/master/unmute")
def unmute_master() -> dict:
    """Unmute la sortie globale."""
    engine, error = _mixer()
    if error is not None:
        return error
    try:
        engine.unmute()
        return {"result": "master_unmuted"}
    except Exception as e:
        return {"error": str(e)}

def start_api():
    import uvicorn
    uvicorn.run(app, host=host, port=port)
