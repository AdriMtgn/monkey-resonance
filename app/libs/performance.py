"""Contrôle de performance : presets, bypass, looper et mappings MIDI.

Ce module est volontairement indépendant du matériel et du serveur HTTP/MCP :

- il ne fait jamais de ``read()``/``write()`` audio ;
- il ne touche au moteur que via les méthodes publiques d'``AudioStream``
  (``load_effects``, ``set_effect_enabled``, looper) ;
- les mappings MIDI sont des données sauvegardables, comme les chaînes
  d'effets, dans ``/monkey-resonance/saved_midi_maps/``.

Un listener MIDI (voir ``midi_control.py``) se contente d'appeler
``dispatch_event()``. La même méthode sert au simulateur MCP/REST, ce qui
permet de tester tout le mapping sans pédale physique.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import audio_stream as audio_stream_module
from .utils import APP_BASE_FOLDER, APP_FOLDERS

logger = logging.getLogger(__name__)

midi_maps_folder = os.path.join(APP_BASE_FOLDER, APP_FOLDERS["SAVED_MIDI_MAPS"])

# Canaux MIDI internes : 0..15 (le canal 0 correspond au canal MIDI 1).
MIDI_CHANNEL_MAX = 15
MIDI_VALUE_MAX = 127

SOURCE_TYPES = frozenset(
    {"program_change", "control_change", "note_on", "note_off"}
)
CC_MODES = frozenset({"press", "release", "toggle", "value"})
ACTION_TYPES = frozenset(
    {
        "preset",
        "next_preset",
        "previous_preset",
        "toggle_effect",
        "set_effect_enabled",
        "loop_toggle",
        "loop_record",
        "loop_play",
        "loop_stop",
        "mute_input",
        "unmute_input",
        "set_input_volume",
        "set_master_volume",
    }
)
VOLUME_ACTIONS = frozenset({"set_input_volume", "set_master_volume"})


def _safe_name(name: str) -> str:
    """Nettoie un nom de preset/mapping et interdit toute traversée de chemin."""
    if not isinstance(name, str):
        raise TypeError("le nom doit être une chaîne")
    name = name.strip().removesuffix(".json")
    if not name or name in {".", ".."} or Path(name).name != name:
        raise ValueError(f"nom invalide : {name!r}")
    if re.search(r"[/\\]", name):
        raise ValueError(f"nom invalide : {name!r}")
    return name


def _midi_int(value: object, label: str, maximum: int = MIDI_VALUE_MAX) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} doit être un entier") from exc
    if number < 0 or number > maximum:
        raise ValueError(f"{label} hors plage (0..{maximum}) : {number}")
    return number


def _read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def list_presets(folder: str | None = None) -> list[str]:
    """Liste les chaînes d'effets valides de ``saved_effects/``.

    Seuls les JSON contenant une liste ``effect_chain`` (ou une liste legacy)
    sont retenus. Les WAV et fichiers invalides sont ignorés.
    """
    root = Path(folder or audio_stream_module.effects_folder)
    if not root.is_dir():
        return []
    presets: list[str] = []
    for path in sorted(root.glob("*.json")):
        try:
            data = _read_json(path)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Preset ignoré (%s) : %s", path.name, exc)
            continue
        chain = (
            data
            if isinstance(data, list)
            else data.get("effect_chain")
            if isinstance(data, dict)
            else None
        )
        if isinstance(chain, list):
            presets.append(path.stem)
        else:
            logger.warning("Preset ignoré (format invalide) : %s", path.name)
    return presets


# ----------------------------------------------------------------------
# Événements et mappings MIDI
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class MidiEvent:
    """Message MIDI normalisé (canal 0..15)."""

    type: str
    channel: int = 0
    number: int | None = None
    controller: int | None = None
    value: int = 0

    def __post_init__(self) -> None:
        if self.type not in SOURCE_TYPES:
            raise ValueError(f"type MIDI inconnu : {self.type!r}")
        _midi_int(self.channel, "channel", MIDI_CHANNEL_MAX)
        _midi_int(self.value, "value")
        if self.number is not None:
            _midi_int(self.number, "number")
        if self.controller is not None:
            _midi_int(self.controller, "controller")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MidiEvent:
        if not isinstance(data, dict):
            raise TypeError("un événement MIDI doit être un dictionnaire")
        event_type = str(data.get("type", data.get("kind", ""))).strip()
        if event_type not in SOURCE_TYPES:
            raise ValueError(f"type MIDI inconnu : {event_type!r}")
        raw_value = data.get("value")
        if raw_value is None:
            # Simulation : une pression sans valeur explicite équivaut à 127.
            value = 127 if event_type in {"note_on", "control_change"} else 0
        else:
            value = int(raw_value)
        if event_type == "note_on" and value == 0:
            # Même normalisation que le parseur MIDI réel.
            event_type = "note_off"
        return cls(
            type=event_type,
            channel=int(data.get("channel", 0)),
            number=(
                int(data["number"])
                if data.get("number") is not None
                else None
            ),
            controller=(
                int(data["controller"])
                if data.get("controller") is not None
                else None
            ),
            value=value,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": self.type,
            "channel": self.channel,
            "value": self.value,
        }
        if self.number is not None:
            result["number"] = self.number
        if self.controller is not None:
            result["controller"] = self.controller
        return result


@dataclass(frozen=True, slots=True)
class MidiSource:
    """Description d'un message MIDI déclencheur."""

    type: str
    number: int | None = None
    controller: int | None = None
    channel: int | None = None
    mode: str = "press"
    threshold: int = 64

    def __post_init__(self) -> None:
        if self.type not in SOURCE_TYPES:
            raise ValueError(f"type MIDI inconnu : {self.type!r}")
        if self.channel is not None:
            _midi_int(self.channel, "channel", MIDI_CHANNEL_MAX)
        if self.mode not in CC_MODES:
            raise ValueError(f"mode MIDI inconnu : {self.mode!r}")
        _midi_int(self.threshold, "threshold")
        if self.type == "control_change":
            if self.controller is None:
                raise ValueError("control_change exige un controller")
            _midi_int(self.controller, "controller")
        elif self.number is None:
            raise ValueError(f"{self.type} exige un numéro")
        else:
            _midi_int(self.number, "number")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MidiSource:
        if not isinstance(data, dict):
            raise TypeError("une source MIDI doit être un dictionnaire")
        return cls(
            type=str(data.get("type", "")).strip(),
            number=(
                int(data["number"])
                if data.get("number") is not None
                else None
            ),
            controller=(
                int(data["controller"])
                if data.get("controller") is not None
                else None
            ),
            channel=(
                int(data["channel"])
                if data.get("channel") is not None
                else None
            ),
            mode=str(data.get("mode", "press")),
            threshold=int(data.get("threshold", 64)),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type, "mode": self.mode}
        if self.number is not None:
            result["number"] = self.number
        if self.controller is not None:
            result["controller"] = self.controller
        if self.channel is not None:
            result["channel"] = self.channel
        if self.threshold != 64:
            result["threshold"] = self.threshold
        return result

    def matches(self, event: MidiEvent, default_channel: int | None = None) -> bool:
        channel = self.channel if self.channel is not None else default_channel
        if channel is not None and event.channel != channel:
            return False
        if self.type == "program_change":
            return event.type == "program_change" and event.number == self.number
        if self.type == "control_change":
            return (
                event.type == "control_change"
                and event.controller == self.controller
            )
        if self.type == "note_off":
            return event.type == "note_off" and event.number == self.number
        # note_on : une source note_on peut aussi servir de release/toggle
        # lorsqu'un note-off arrive (velocity 0 est normalisé par le parseur).
        return event.type in {"note_on", "note_off"} and event.number == self.number


@dataclass(frozen=True, slots=True)
class TriggerAction:
    """Action exécutée par le contrôleur de performance."""

    type: str
    target: str | int | None = None
    enabled: bool | None = None
    input_index: int | None = None
    value: float | None = None

    def __post_init__(self) -> None:
        if self.type not in ACTION_TYPES:
            raise ValueError(f"action inconnue : {self.type!r}")
        if self.type == "preset":
            if not isinstance(self.target, str) or not self.target:
                raise ValueError("preset exige une cible")
        elif self.type in {"toggle_effect", "set_effect_enabled"}:
            if self.target is None:
                raise ValueError(f"{self.type} exige une cible")
            if self.type == "set_effect_enabled" and self.enabled is None:
                raise ValueError("set_effect_enabled exige 'enabled'")
        elif self.type in VOLUME_ACTIONS and self.value is not None and not (
            0.0 <= float(self.value) <= 1.0
        ):
            raise ValueError(f"{self.type} exige une valeur entre 0 et 1")
        if self.input_index is not None and int(self.input_index) < 0:
            raise ValueError("input_index doit être positif")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TriggerAction:
        if not isinstance(data, dict):
            raise TypeError("une action doit être un dictionnaire")
        target = data.get("target")
        if isinstance(target, str) and target.strip().isdigit():
            target = int(target)
        return cls(
            type=str(data.get("type", data.get("action", ""))).strip(),
            target=target,
            enabled=(
                bool(data["enabled"])
                if data.get("enabled") is not None
                else None
            ),
            input_index=(
                int(data["input_index"])
                if data.get("input_index") is not None
                else None
            ),
            value=(
                float(data["value"])
                if data.get("value") is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type}
        if self.target is not None:
            result["target"] = self.target
        if self.enabled is not None:
            result["enabled"] = self.enabled
        if self.input_index is not None:
            result["input_index"] = self.input_index
        if self.value is not None:
            result["value"] = self.value
        return result


@dataclass(slots=True)
class MidiBinding:
    """Association source MIDI -> action."""

    source: MidiSource
    action: TriggerAction
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def __post_init__(self) -> None:
        if not self.id:
            self.id = uuid.uuid4().hex[:8]
        if self.source.mode == "value" and self.action.type not in VOLUME_ACTIONS:
            raise ValueError(
                "le mode 'value' n'est supporté que pour les volumes "
                "(set_input_volume / set_master_volume)"
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MidiBinding:
        if not isinstance(data, dict):
            raise TypeError("un binding doit être un dictionnaire")
        return cls(
            source=MidiSource.from_dict(data.get("source", {})),
            action=TriggerAction.from_dict(data.get("action", {})),
            id=str(data.get("id") or uuid.uuid4().hex[:8]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source.to_dict(),
            "action": self.action.to_dict(),
        }


@dataclass(slots=True)
class MidiMap:
    """Profil de mapping MIDI, sauvegardable comme un preset d'effets."""

    name: str = "live"
    device: str | None = None
    channel: int | None = None
    debounce_ms: int = 150
    input_index: int = 0
    startup_preset: str | None = None
    preset_order: list[str] = field(default_factory=list)
    bindings: list[MidiBinding] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.channel is not None:
            _midi_int(self.channel, "channel", MIDI_CHANNEL_MAX)
        if int(self.debounce_ms) < 0:
            raise ValueError("debounce_ms doit être positif")
        if int(self.input_index) < 0:
            raise ValueError("input_index doit être positif")
        self.debounce_ms = int(self.debounce_ms)
        self.input_index = int(self.input_index)
        ids = [binding.id for binding in self.bindings]
        if len(ids) != len(set(ids)):
            raise ValueError("identifiants de binding dupliqués")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MidiMap:
        if not isinstance(data, dict):
            raise TypeError("un mapping MIDI doit être un dictionnaire")

        # Deux formats acceptés : plat (nouveau) ou avec une section "midi"
        # (comme l'exemple de configuration historique).
        midi = data.get("midi") if isinstance(data.get("midi"), dict) else {}
        merged = {**data, **midi}
        bindings_data = merged.get("bindings", [])
        if not isinstance(bindings_data, list):
            raise TypeError("bindings doit être une liste")
        order_data = merged.get("order")
        if order_data is None:
            order_data = merged.get("preset_order", [])
        if not isinstance(order_data, list):
            raise TypeError("order doit être une liste")
        return cls(
            name=str(merged.get("name", "live")),
            device=(
                str(merged["device"])
                if merged.get("device") is not None
                else None
            ),
            channel=(
                int(merged["channel"])
                if merged.get("channel") is not None
                else None
            ),
            debounce_ms=int(merged.get("debounce_ms", 150)),
            input_index=int(merged.get("input_index", 0)),
            startup_preset=(
                str(merged["startup"])
                if merged.get("startup") is not None
                else (
                    str(merged["startup_preset"])
                    if merged.get("startup_preset") is not None
                    else None
                )
            ),
            preset_order=[str(item) for item in order_data],
            bindings=[MidiBinding.from_dict(item) for item in bindings_data],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "device": self.device,
            "channel": self.channel,
            "debounce_ms": self.debounce_ms,
            "input_index": self.input_index,
            "startup_preset": self.startup_preset,
            "preset_order": list(self.preset_order),
            "bindings": [binding.to_dict() for binding in self.bindings],
        }

    def add_binding(self, binding: MidiBinding) -> MidiBinding:
        if any(existing.id == binding.id for existing in self.bindings):
            raise ValueError(f"binding déjà présent : {binding.id}")
        self.bindings.append(binding)
        return binding

    def remove_binding(self, binding_id: str) -> MidiBinding:
        for index, binding in enumerate(self.bindings):
            if binding.id == binding_id:
                return self.bindings.pop(index)
        raise KeyError(f"binding inconnu : {binding_id}")

    def get_binding(self, binding_id: str) -> MidiBinding:
        for binding in self.bindings:
            if binding.id == binding_id:
                return binding
        raise KeyError(f"binding inconnu : {binding_id}")


# ----------------------------------------------------------------------
# Persistance des profils de mapping
# ----------------------------------------------------------------------
def list_midi_maps(folder: str | None = None) -> list[str]:
    """Liste les profils de mapping valides."""
    root = Path(folder or midi_maps_folder)
    if not root.is_dir():
        return []
    names: list[str] = []
    for path in sorted(root.glob("*.json")):
        try:
            MidiMap.from_dict(_read_json(path))
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
            logger.warning("Mapping ignoré (%s) : %s", path.name, exc)
            continue
        names.append(path.stem)
    return names


def load_midi_map(name: str, folder: str | None = None) -> MidiMap:
    """Charge ``saved_midi_maps/<name>.json``."""
    safe_name = _safe_name(name)
    path = Path(folder or midi_maps_folder) / f"{safe_name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Mapping MIDI introuvable : {path}")
    return MidiMap.from_dict(_read_json(path))


def save_midi_map(mapping: MidiMap, name: str | None = None, folder: str | None = None) -> str:
    """Sauvegarde un profil de mapping et retourne le chemin écrit."""
    safe_name = _safe_name(name or mapping.name)
    root = Path(folder or midi_maps_folder)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{safe_name}.json"
    temporary = path.with_suffix(".json.tmp")
    payload = mapping.to_dict()
    payload["name"] = safe_name
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=4, ensure_ascii=False)
        file.write("\n")
    os.replace(temporary, path)
    logger.info("Mapping MIDI sauvegardé dans %s", path)
    return str(path)


# ----------------------------------------------------------------------
# Contrôleur
# ----------------------------------------------------------------------
class PerformanceController:
    """Contrôleur thread-safe des presets, bypass, looper et événements MIDI."""

    def __init__(
        self,
        inputs: list[Any],
        *,
        engine: Any | None = None,
        input_index: int = 0,
        mapping: MidiMap | None = None,
    ) -> None:
        self._inputs = inputs
        self._engine = engine
        self._default_input_index = int(input_index)
        self._mapping = mapping or MidiMap(input_index=input_index)
        self._default_input_index = int(self._mapping.input_index)
        self._lock = threading.RLock()
        self._current_preset: str | None = None
        self._last_recording: dict[int, str] = {}
        self._last_event: dict[str, Any] | None = None
        self._last_action: dict[str, Any] | None = None
        self._learn = False
        self._learned_event: dict[str, Any] | None = None
        self._pressed: dict[str, bool] = {}
        self._last_trigger: dict[str, float] = {}
        self._midi_status: dict[str, Any] = {
            "connected": False,
            "device": None,
            "error": None,
            "messages": 0,
        }

    # -- état général -------------------------------------------------
    @property
    def mapping(self) -> MidiMap:
        with self._lock:
            return self._mapping

    @property
    def current_preset(self) -> str | None:
        with self._lock:
            return self._current_preset

    @property
    def device_spec(self) -> str | None:
        with self._lock:
            return self._mapping.device

    def _input_at(self, input_index: int | None = None) -> Any:
        index = self._default_input_index if input_index is None else int(input_index)
        if index < 0 or index >= len(self._inputs):
            raise ValueError(f"input invalide : {index}")
        return self._inputs[index]

    def list_presets(self) -> list[str]:
        return list_presets()

    def preset_order(self) -> list[str]:
        with self._lock:
            order = list(self._mapping.preset_order)
        available = self.list_presets()
        if order:
            return [name for name in order if name in available]
        return available

    # -- presets ------------------------------------------------------
    def apply_preset(
        self,
        name: str,
        *,
        input_index: int | None = None,
        keep_volume: bool = True,
    ) -> dict[str, Any]:
        """Charge un preset sur une piste, en conservant son fader par défaut."""
        preset = _safe_name(name)
        available = self.list_presets()
        if preset not in available:
            raise FileNotFoundError(f"Preset introuvable : {preset}")
        with self._lock:
            inp = self._input_at(input_index)
            volume = float(getattr(inp, "global_volume", 1.0))
            inp.load_effects(preset)
            if keep_volume:
                inp.global_volume = volume
            self._current_preset = preset
            return {
                "result": "preset_loaded",
                "preset": preset,
                "input_index": (
                    self._default_input_index
                    if input_index is None
                    else int(input_index)
                ),
                "volume": round(float(getattr(inp, "global_volume", 1.0)), 4),
                "effects": getattr(inp, "effects_chain", []),
            }

    def next_preset(self, *, input_index: int | None = None) -> dict[str, Any]:
        order = self.preset_order()
        if not order:
            raise FileNotFoundError("Aucun preset disponible")
        with self._lock:
            current = self._current_preset
        if current not in order:
            return self.apply_preset(order[0], input_index=input_index)
        return self.apply_preset(
            order[(order.index(current) + 1) % len(order)],
            input_index=input_index,
        )

    def previous_preset(self, *, input_index: int | None = None) -> dict[str, Any]:
        order = self.preset_order()
        if not order:
            raise FileNotFoundError("Aucun preset disponible")
        with self._lock:
            current = self._current_preset
        if current not in order:
            return self.apply_preset(order[-1], input_index=input_index)
        return self.apply_preset(
            order[(order.index(current) - 1) % len(order)],
            input_index=input_index,
        )

    # -- effets -------------------------------------------------------
    def toggle_effect(
        self,
        target: str | int,
        *,
        input_index: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            inp = self._input_at(input_index)
            positions = inp.effect_positions(target)
            if not positions:
                raise ValueError(f"Effet introuvable dans la chaîne : {target!r}")
            result = inp.toggle_effect(positions[0])
            return {"result": "effect_toggled", **result}

    def set_effect_enabled(
        self,
        target: str | int,
        enabled: bool,
        *,
        input_index: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            inp = self._input_at(input_index)
            positions = inp.effect_positions(target)
            if not positions:
                raise ValueError(f"Effet introuvable dans la chaîne : {target!r}")
            result = inp.set_effect_enabled(positions[0], enabled)
            return {"result": "effect_enabled_set", **result}

    # -- looper -------------------------------------------------------
    def loop_toggle(self, *, input_index: int | None = None) -> dict[str, Any]:
        """Un seul pad : enregistre, puis lit en boucle, puis arrête."""
        with self._lock:
            inp = self._input_at(input_index)
            index = (
                self._default_input_index
                if input_index is None
                else int(input_index)
            )
            if bool(getattr(inp, "recording", False)):
                filepath = inp.stop_recording()
                self._last_recording[index] = filepath
                playback = inp.play_recording(filepath, loop=True)
                return {
                    "result": "playing",
                    "recording": filepath,
                    "playback": playback,
                }
            if getattr(inp, "playback", None) is not None:
                stopped = inp.stop_playback()
                return {"result": "stopped", "playback": stopped}
            inp.start_recording()
            return {"result": "recording"}

    def loop_record(self, *, input_index: int | None = None) -> dict[str, Any]:
        with self._lock:
            inp = self._input_at(input_index)
            if bool(getattr(inp, "recording", False)):
                raise RuntimeError("Enregistrement déjà en cours")
            if getattr(inp, "playback", None) is not None:
                inp.stop_playback()
            filepath = inp.start_recording()
            return {"result": "recording", "recording": filepath}

    def loop_play(
        self,
        *,
        input_index: int | None = None,
        filename: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            inp = self._input_at(input_index)
            index = (
                self._default_input_index
                if input_index is None
                else int(input_index)
            )
            path = filename or self._last_recording.get(index)
            if not path:
                path = self._latest_recording()
            if not path:
                raise FileNotFoundError("Aucun enregistrement à lire")
            playback = inp.play_recording(path, loop=True)
            return {"result": "playing", "playback": playback}

    def loop_stop(self, *, input_index: int | None = None) -> dict[str, Any]:
        with self._lock:
            inp = self._input_at(input_index)
            stopped = inp.stop_playback()
            return {
                "result": "stopped" if stopped else "no_playback",
                "playback": stopped,
            }

    def _latest_recording(self) -> str | None:
        root = Path(audio_stream_module.records_folder)
        if not root.is_dir():
            return None
        candidates = sorted(
            root.glob("*.wav"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return str(candidates[0]) if candidates else None

    # -- mapping ------------------------------------------------------
    def get_mapping(self) -> MidiMap:
        with self._lock:
            return self._mapping

    def get_mapping_dict(self) -> dict[str, Any]:
        with self._lock:
            return self._mapping.to_dict()

    def set_mapping(self, mapping: MidiMap) -> dict[str, Any]:
        with self._lock:
            self._mapping = mapping
            self._default_input_index = int(mapping.input_index)
            self._pressed.clear()
            self._last_trigger.clear()
        return {"result": "mapping_set", "mapping": mapping.to_dict()}

    def configure_mapping(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Met à jour les métadonnées du mapping actif (ordre, device, etc.).

        Les clés absentes de ``changes`` restent inchangées. Les valeurs sont
        validées en reconstruisant un ``MidiMap`` : aucune écriture partielle
        n'est appliquée si une valeur est invalide.
        """
        if not isinstance(changes, dict):
            raise TypeError("changes doit être un dictionnaire")
        with self._lock:
            data = self._mapping.to_dict()
        data.update(changes)
        mapping = MidiMap.from_dict(data)
        return self.set_mapping(mapping)

    def add_binding(
        self,
        source: dict[str, Any],
        action: dict[str, Any],
        *,
        binding_id: str | None = None,
    ) -> dict[str, Any]:
        binding = MidiBinding(
            source=MidiSource.from_dict(source),
            action=TriggerAction.from_dict(action),
            id=binding_id or uuid.uuid4().hex[:8],
        )
        with self._lock:
            self._mapping.add_binding(binding)
        return {"result": "binding_added", "binding": binding.to_dict()}

    def update_binding(
        self,
        binding_id: str,
        *,
        source: dict[str, Any] | None = None,
        action: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            binding = self._mapping.get_binding(binding_id)
            new_source = (
                MidiSource.from_dict(source) if source is not None else binding.source
            )
            new_action = (
                TriggerAction.from_dict(action) if action is not None else binding.action
            )
            updated = MidiBinding(
                source=new_source,
                action=new_action,
                id=binding.id,
            )
            index = self._mapping.bindings.index(binding)
            self._mapping.bindings[index] = updated
        return {"result": "binding_updated", "binding": updated.to_dict()}

    def remove_binding(self, binding_id: str) -> dict[str, Any]:
        with self._lock:
            removed = self._mapping.remove_binding(binding_id)
            self._pressed.pop(binding_id, None)
            self._last_trigger.pop(binding_id, None)
        return {"result": "binding_removed", "binding": removed.to_dict()}

    def save_mapping(self, name: str | None = None) -> dict[str, Any]:
        with self._lock:
            mapping = self._mapping
        path = save_midi_map(mapping, name)
        return {"result": "mapping_saved", "file": path}

    def load_mapping(self, name: str) -> dict[str, Any]:
        mapping = load_midi_map(name)
        return self.set_mapping(mapping)

    def list_mappings(self) -> list[str]:
        return list_midi_maps()

    # -- événements MIDI ----------------------------------------------
    def dispatch_event(self, event: MidiEvent) -> dict[str, Any]:
        """Applique les bindings correspondants à un événement MIDI."""
        with self._lock:
            self._midi_status["messages"] = int(self._midi_status["messages"]) + 1
            self._last_event = event.to_dict()
            if self._learn:
                # On capture le premier message puis on sort du mode learn :
                # un pad envoie souvent Note On + Note Off, on ne veut pas que
                # le Note Off écrase la source apprise.
                self._learned_event = event.to_dict()
                self._learn = False
                return {"result": "learned", "event": event.to_dict()}

            mapping = self._mapping
            triggered: list[dict[str, Any]] = []
            errors: list[dict[str, Any]] = []
            for binding in tuple(mapping.bindings):
                try:
                    if not self._should_fire(binding, mapping, event):
                        continue
                    result = self._dispatch_action(binding.action, event)
                    triggered.append(
                        {
                            "binding": binding.id,
                            "action": binding.action.to_dict(),
                            "result": result,
                        }
                    )
                except Exception as exc:
                    logger.exception("Binding MIDI %s en erreur", binding.id)
                    errors.append({"binding": binding.id, "error": str(exc)})
            self._last_action = {
                "event": event.to_dict(),
                "triggered": triggered,
                "errors": errors,
            }
            return self._last_action.copy()

    def _should_fire(
        self,
        binding: MidiBinding,
        mapping: MidiMap,
        event: MidiEvent,
    ) -> bool:
        source = binding.source
        if not source.matches(event, mapping.channel):
            return False

        now = time.monotonic()
        debounce_s = mapping.debounce_ms / 1000.0
        last = self._last_trigger.get(binding.id, 0.0)

        if source.mode == "value":
            self._last_trigger[binding.id] = now
            return True

        if source.type in {"program_change", "note_off"}:
            if debounce_s and now - last < debounce_s:
                return False
            self._last_trigger[binding.id] = now
            return True

        pressed = self._is_pressed(source, event)
        was_pressed = self._pressed.get(binding.id, False)
        self._pressed[binding.id] = pressed

        fire = False
        if source.mode == "press":
            fire = pressed and not was_pressed
        elif source.mode == "release":
            fire = not pressed and was_pressed
        elif source.mode == "toggle":
            fire = pressed and not was_pressed

        if not fire:
            return False
        if debounce_s and now - last < debounce_s:
            return False
        self._last_trigger[binding.id] = now
        return True

    @staticmethod
    def _is_pressed(source: MidiSource, event: MidiEvent) -> bool:
        if event.type == "note_on":
            return event.value > 0
        if event.type == "note_off":
            return False
        if event.type == "control_change":
            return event.value >= source.threshold
        return True

    def _dispatch_action(
        self,
        action: TriggerAction,
        event: MidiEvent,
    ) -> dict[str, Any]:
        if action.type == "preset":
            return self.apply_preset(
                str(action.target),
                input_index=action.input_index,
            )
        if action.type == "next_preset":
            return self.next_preset(input_index=action.input_index)
        if action.type == "previous_preset":
            return self.previous_preset(input_index=action.input_index)
        if action.type == "toggle_effect":
            return self.toggle_effect(
                action.target,  # type: ignore[arg-type]
                input_index=action.input_index,
            )
        if action.type == "set_effect_enabled":
            return self.set_effect_enabled(
                action.target,  # type: ignore[arg-type]
                bool(action.enabled),
                input_index=action.input_index,
            )
        if action.type == "loop_toggle":
            return self.loop_toggle(input_index=action.input_index)
        if action.type == "loop_record":
            return self.loop_record(input_index=action.input_index)
        if action.type == "loop_play":
            return self.loop_play(input_index=action.input_index)
        if action.type == "loop_stop":
            return self.loop_stop(input_index=action.input_index)
        if action.type == "mute_input":
            inp = self._input_at(action.input_index)
            inp.mute()
            return {"result": "input_muted"}
        if action.type == "unmute_input":
            inp = self._input_at(action.input_index)
            inp.unmute()
            return {"result": "input_unmuted"}
        if action.type == "set_input_volume":
            inp = self._input_at(action.input_index)
            inp.global_volume = self._event_value(action, event)
            return {
                "result": "input_volume_set",
                "volume": round(float(inp.global_volume), 4),
            }
        if action.type == "set_master_volume":
            if self._engine is None:
                raise RuntimeError("Moteur audio indisponible")
            volume = self._event_value(action, event)
            self._engine.set_master_volume(volume)
            return {"result": "master_volume_set", "volume": volume}
        raise ValueError(f"action non implémentée : {action.type}")

    @staticmethod
    def _event_value(action: TriggerAction, event: MidiEvent) -> float:
        if action.value is not None:
            return float(action.value)
        return max(0.0, min(float(event.value) / MIDI_VALUE_MAX, 1.0))

    # -- learn / statut ----------------------------------------------
    def start_learn(self) -> dict[str, Any]:
        with self._lock:
            self._learn = True
            self._learned_event = None
        return {"result": "learning", "learn": True}

    def stop_learn(self) -> dict[str, Any]:
        with self._lock:
            self._learn = False
            learned = self._learned_event
        return {"result": "learning_stopped", "learn": False, "event": learned}

    def learn_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "learn": self._learn,
                "event": self._learned_event,
                "last_event": self._last_event,
            }

    def set_midi_status(self, **status: Any) -> None:
        with self._lock:
            self._midi_status.update(status)

    def midi_status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._midi_status)

    def last_event(self) -> dict[str, Any] | None:
        with self._lock:
            return self._last_event

    def last_action(self) -> dict[str, Any] | None:
        with self._lock:
            return self._last_action

    def status(self) -> dict[str, Any]:
        with self._lock:
            current = self._current_preset
            mapping = self._mapping.to_dict()
            midi = dict(self._midi_status)
            learn = {
                "learn": self._learn,
                "event": self._learned_event,
            }
        return {
            "current_preset": current,
            "presets": self.list_presets(),
            "preset_order": self.preset_order(),
            "mapping": mapping,
            "midi": midi,
            "learn": learn,
            "last_event": self.last_event(),
            "last_action": self.last_action(),
        }

    # -- démarrage ----------------------------------------------------
    def load_startup_mapping(self) -> dict[str, Any]:
        """Charge le mapping configuré par l'environnement ou ``triggers.json``."""
        explicit = os.environ.get("MKR_MIDI_CONFIG")
        map_name = os.environ.get("MKR_MIDI_MAP")
        mapping: MidiMap | None = None
        source: str | None = None

        if explicit:
            path = Path(explicit)
            if path.is_file():
                mapping = MidiMap.from_dict(_read_json(path))
                source = str(path)
        elif map_name:
            mapping = load_midi_map(map_name)
            source = map_name
        else:
            path = Path(APP_BASE_FOLDER) / "triggers.json"
            if path.is_file():
                mapping = MidiMap.from_dict(_read_json(path))
                source = str(path)

        if mapping is None:
            return {"result": "no_mapping"}
        self.set_mapping(mapping)
        return {"result": "mapping_loaded", "source": source}

    def apply_startup_preset(self) -> dict[str, Any] | None:
        """Applique le preset de démarrage s'il est configuré et valide."""
        with self._lock:
            name = os.environ.get("MKR_START_PRESET") or self._mapping.startup_preset
        if not name:
            return None
        try:
            return self.apply_preset(name)
        except (FileNotFoundError, OSError, ValueError) as exc:
            logger.warning("Preset de démarrage ignoré (%s) : %s", name, exc)
            return {"error": str(exc)}
