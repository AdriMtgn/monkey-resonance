"""Découverte et résolution des périphériques audio via Pedalboard/JUCE.

Pedalboard expose les noms de devices ALSA/JUCE, y compris dans le container
(contrairement à PortAudio qui ne voit aucun device ici). En entrée comme en
sortie, on préfère le chemin matériel direct (« Direct hardware device without
any conversions ») : il évite PipeWire/Pulse et la période du ``dsnoop``
(1024 frames), donc la latence la plus faible.

La carte étant alors ouverte en exclusif, l'enregistrement et l'analyse
n'ouvrent plus de capture secondaire : ils sont alimentés par le moteur
(listeners / file bornée). ``prefer_shared_capture`` reste disponible pour les
configurations qui voudraient explicitement le ``dsnoop``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from pedalboard.io import AudioStream

logger = logging.getLogger(__name__)

DIRECT_HARDWARE_MARKER = "direct hardware device without any conversions"
SHARED_CAPTURE_MARKER = "direct sample snooping device"


@dataclass(frozen=True, slots=True)
class AudioConfig:
    """Configuration du moteur audio, lue depuis l'environnement."""

    input_device: str
    output_device: str
    # Conservé pour compatibilité : l'enregistrement est alimenté par le moteur.
    record_device: str | None = None
    sample_rate: int = 48000
    buffer_size: int = 128
    input_channels: int = 2
    output_channels: int = 2
    start_muted: bool = False
    global_volume: float = 1.0
    master_volume: float = 1.0
    allow_feedback: bool = False
    # Configuration du mixer multi-pistes (voir libs/mixer.py).
    # AUDIO_INPUTS  : "nom:canal[,canal][;...]" (défaut : une piste mono/canal)
    # AUDIO_OUTPUTS : "nom:gauche[,droite][;...]" (défaut : un bus main 0/1)
    input_layout: str = ""
    output_layout: str = ""

    @property
    def buffer_latency_ms(self) -> float:
        """Latence d'un buffer, dans un sens (aller ou retour)."""
        return (self.buffer_size / self.sample_rate) * 1000.0

    @property
    def round_trip_latency_ms(self) -> float:
        """Estimation aller-retour (deux buffers, hors latence matérielle)."""
        return self.buffer_latency_ms * 2.0


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _as_device_dict(
    names: list[str], default_name: str | None, kind: str
) -> dict[int, dict[str, object]]:
    return {
        index: {
            "index": index,
            "name": name,
            "kind": kind,
            "default": name == default_name,
            "direct_hardware": DIRECT_HARDWARE_MARKER in name.lower(),
        }
        for index, name in enumerate(names)
    }


def list_devices() -> tuple[dict[int, dict[str, object]], dict[int, dict[str, object]]]:
    """Retourne ``(entrées, sorties)`` indexées par numéro de device."""
    inputs = _as_device_dict(
        AudioStream.input_device_names,
        AudioStream.default_input_device_name,
        "input",
    )
    outputs = _as_device_dict(
        AudioStream.output_device_names,
        AudioStream.default_output_device_name,
        "output",
    )
    return inputs, outputs


def _prefer_direct(
    devices: dict[int, dict[str, object]],
) -> dict[str, object]:
    return min(
        devices.values(),
        key=lambda device: (
            not bool(device["direct_hardware"]),
            int(device["index"]),
        ),
    )


def _device_card(name: str) -> str:
    """Préfixe carte d'un nom ALSA/JUCE (avant la première virgule)."""
    return name.split(",", 1)[0].strip().lower()


def _shared_capture_variant(
    device: dict[str, object],
    devices: dict[int, dict[str, object]],
) -> dict[str, object] | None:
    """Trouve le device ``dsnoop`` de la même carte, s'il existe.

    ``dsnoop`` permet à plusieurs clients de capturer l'entrée en même temps :
    c'est ce qui rend l'enregistrement possible pendant que le stream principal
    tourne. Sans lui, la carte est ouverte en exclusif.
    """
    card = _device_card(str(device["name"]))
    candidates = [
        candidate
        for candidate in devices.values()
        if _device_card(str(candidate["name"])) == card
        and SHARED_CAPTURE_MARKER in str(candidate["name"]).lower()
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: int(candidate["index"]))


def _auto_device(
    devices: dict[int, dict[str, object]],
    kind: str,
    *,
    prefer_shared_capture: bool = False,
) -> dict[str, object]:
    audiobox = [
        device
        for device in devices.values()
        if "audiobox" in str(device["name"]).lower()
    ]
    if audiobox:
        if kind == "input" and prefer_shared_capture:
            shared = [
                device
                for device in audiobox
                if SHARED_CAPTURE_MARKER in str(device["name"]).lower()
            ]
            if shared:
                return min(shared, key=lambda device: int(device["index"]))
        direct = [
            device
            for device in audiobox
            if DIRECT_HARDWARE_MARKER in str(device["name"]).lower()
        ]
        if direct:
            return min(direct, key=lambda device: int(device["index"]))
        return min(audiobox, key=lambda device: int(device["index"]))

    defaults = [device for device in devices.values() if device["default"]]
    if defaults:
        return defaults[0]

    return min(devices.values(), key=lambda device: int(device["index"]))


def resolve_device_name(
    preferred: str | int | None,
    devices: dict[int, dict[str, object]],
    kind: str,
    *,
    prefer_shared_capture: bool = False,
) -> str:
    """Résout un device par index, nom exact, sous-chaîne, ou automatiquement.

    ``prefer_shared_capture`` (entrées uniquement) bascule vers le device
    ``dsnoop`` de la même carte quand il existe, afin que l'enregistrement
    puisse ouvrir une seconde capture sans voler la carte au stream principal.
    Un nom exact ou un index explicite n'est jamais remplacé.
    """
    if not devices:
        raise RuntimeError(
            f"Aucun périphérique audio {kind} détecté. "
            "Vérifie que /dev/snd est partagé avec le container."
        )

    def _finalize(device: dict[str, object]) -> str:
        if kind == "input" and prefer_shared_capture:
            shared = _shared_capture_variant(device, devices)
            if shared is not None:
                return str(shared["name"])
        return str(device["name"])

    # Les variables d'environnement arrivent en str : accepte "2" comme index.
    if isinstance(preferred, str) and preferred.strip().isdigit():
        preferred = int(preferred.strip())

    if isinstance(preferred, int):
        try:
            return str(devices[preferred]["name"])
        except KeyError as exc:
            available = ", ".join(
                f"{index}={device['name']}" for index, device in devices.items()
            )
            raise ValueError(
                f"Périphérique {kind} {preferred} introuvable. Disponibles : {available}"
            ) from exc

    if preferred:
        needle = str(preferred).strip()
        exact = [
            device
            for device in devices.values()
            if str(device["name"]).lower() == needle.lower()
        ]
        if exact:
            return str(exact[0]["name"])

        matches = [
            device
            for device in devices.values()
            if needle.lower() in str(device["name"]).lower()
        ]
        if matches:
            chosen = _prefer_direct(
                {int(device["index"]): device for device in matches}
            )
            if len(matches) > 1:
                logger.info(
                    "Plusieurs périphériques %s correspondent à %r, choisi : %s",
                    kind,
                    preferred,
                    chosen["name"],
                )
            return _finalize(chosen)

        available = ", ".join(
            f"{index}={device['name']}" for index, device in devices.items()
        )
        raise ValueError(
            f"Périphérique {kind} {preferred!r} introuvable. Disponibles : {available}"
        )

    return _finalize(
        _auto_device(
            devices,
            kind,
            prefer_shared_capture=prefer_shared_capture,
        )
    )


def load_config() -> AudioConfig:
    """Construit la configuration depuis les variables d'environnement.

    Variables supportées :
      AUDIO_INPUT_DEVICE / AUDIO_OUTPUT_DEVICE (nom, sous-chaîne ou index)
      AUDIO_RECORD_DEVICE (conservé ; l'enregistrement est alimenté par le moteur)
      AUDIO_SAMPLE_RATE (défaut 48000)
      AUDIO_BUFFER_SIZE (défaut 128 ; 64 validé sur AudioBox USB 96)
      AUDIO_INPUT_CHANNELS / AUDIO_OUTPUT_CHANNELS (défaut 2)
      AUDIO_START_MUTED (défaut 0)
      AUDIO_GLOBAL_VOLUME (défaut 1.0)
      AUDIO_MASTER_VOLUME (défaut 1.0)
      AUDIO_ALLOW_FEEDBACK (défaut 0)
      AUDIO_INPUTS / AUDIO_OUTPUTS (mixer multi-pistes, voir libs/mixer.py)
    """
    inputs, outputs = list_devices()

    input_device = resolve_device_name(
        os.environ.get("AUDIO_INPUT_DEVICE"),
        inputs,
        "input",
    )
    output_device = resolve_device_name(
        os.environ.get("AUDIO_OUTPUT_DEVICE"), outputs, "output"
    )
    record_preference = os.environ.get("AUDIO_RECORD_DEVICE")
    record_device = (
        resolve_device_name(record_preference, inputs, "input")
        if record_preference
        else input_device
    )

    global_volume = float(os.environ.get("AUDIO_GLOBAL_VOLUME", "1.0"))
    return AudioConfig(
        input_device=input_device,
        output_device=output_device,
        record_device=record_device,
        sample_rate=int(os.environ.get("AUDIO_SAMPLE_RATE", "48000")),
        buffer_size=int(os.environ.get("AUDIO_BUFFER_SIZE", "128")),
        input_channels=int(os.environ.get("AUDIO_INPUT_CHANNELS", "2")),
        output_channels=int(os.environ.get("AUDIO_OUTPUT_CHANNELS", "2")),
        start_muted=_env_bool("AUDIO_START_MUTED", False),
        # AUDIO_GLOBAL_VOLUME reste l'alias historique du master.
        global_volume=global_volume,
        master_volume=float(
            os.environ.get("AUDIO_MASTER_VOLUME", str(global_volume))
        ),
        allow_feedback=_env_bool("AUDIO_ALLOW_FEEDBACK", False),
        input_layout=os.environ.get("AUDIO_INPUTS", ""),
        output_layout=os.environ.get("AUDIO_OUTPUTS", ""),
    )
