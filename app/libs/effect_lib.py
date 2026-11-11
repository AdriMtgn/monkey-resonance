"""Catalogue d'effets Pedalboard et compatibilité avec les chemins pyo.

Les chaînes sauvegardées par l'ancien moteur pyo référencent des classes comme
``pyo.lib.effects.Chorus``. Ce module les traduit vers les plugins Pedalboard
équivalents, en conservant les paramètres d'origine dans les fichiers JSON.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pedalboard
from pedalboard import (
    Chorus,
    Compressor,
    Delay,
    Distortion,
    Gain,
    HighpassFilter,
    LadderFilter,
    LowpassFilter,
    NoiseGate,
    Reverb,
)

logger = logging.getLogger(__name__)

Params = dict[str, Any]
PluginList = list[pedalboard.Plugin]


class CustomDelay(Delay):
    """Delay compatible avec l'API historique de ``libs.effect_lib``."""

    def __init__(
        self,
        delay_time: float = 0.5,
        feedback: float = 0.5,
        wet_level: float = 0.5,
    ) -> None:
        super().__init__(
            delay_seconds=delay_time,
            feedback=feedback,
            mix=wet_level,
        )

    def setDelayTime(self, delay_time: float) -> None:
        self.delay_seconds = delay_time

    def setFeedback(self, feedback: float) -> None:
        self.feedback = feedback

    def setWetLevel(self, wet_level: float) -> None:
        self.mix = wet_level

    def getDelayTime(self) -> float:
        return float(self.delay_seconds)

    def getFeedback(self) -> float:
        return float(self.feedback)

    def getWetLevel(self) -> float:
        return float(self.mix)


@dataclass(slots=True)
class EffectSlot:
    """Un effet de la chaîne, avec ses plugins Pedalboard concrets."""

    path: str
    params: Params
    plugins: PluginList
    # ``False`` = bypass : les plugins restent construits (donc un réactiver
    # est immédiat) mais ne sont pas inclus dans le Pedalboard traité.
    enabled: bool = True

    @classmethod
    def create(
        cls,
        path: str,
        params: Params | None = None,
        *,
        enabled: bool = True,
    ) -> EffectSlot:
        clean_params = dict(params or {})
        return cls(
            path=path,
            params=clean_params,
            plugins=build_plugins(path, clean_params),
            enabled=bool(enabled),
        )

    def rebuild(self) -> None:
        self.plugins = build_plugins(self.path, self.params)

    def descriptor(self) -> dict[str, object]:
        return {
            "effect": self.path,
            "params": dict(self.params),
            "enabled": self.enabled,
        }


def _float_param(params: Params, name: str, default: float) -> float:
    value = params.get(name, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning("Paramètre %s invalide (%r), valeur par défaut %s", name, value, default)
        return default


def _gain_from_mul(params: Params) -> PluginList:
    """Traduit le paramètre pyo ``mul`` (facteur linéaire) en Gain Pedalboard."""
    if "mul" not in params:
        return []
    try:
        mul = float(params["mul"])
    except (TypeError, ValueError):
        logger.warning("Paramètre mul invalide (%r), ignoré", params["mul"])
        return []
    if mul <= 0:
        return [Gain(gain_db=-100.0)]
    if math.isclose(mul, 1.0):
        return []
    return [Gain(gain_db=20.0 * math.log10(mul))]


def _compress(params: Params) -> PluginList:
    return [
        Compressor(
            threshold_db=_float_param(params, "thresh", -20.0),
            ratio=_float_param(params, "ratio", 4.0),
            attack_ms=_float_param(params, "risetime", 0.01) * 1000.0,
            release_ms=_float_param(params, "falltime", 0.05) * 1000.0,
        ),
        *_gain_from_mul(params),
    ]


def _gate(params: Params) -> PluginList:
    return [
        NoiseGate(
            threshold_db=_float_param(params, "thresh", -80.0),
            ratio=_float_param(params, "ratio", 10.0),
            attack_ms=_float_param(params, "risetime", 0.001) * 1000.0,
            release_ms=_float_param(params, "falltime", 0.2) * 1000.0,
        ),
        *_gain_from_mul(params),
    ]


def _distortion(params: Params) -> PluginList:
    # pyo Disto.drive est normalisé 0..1 ; Pedalboard attend des dB.
    drive = min(max(_float_param(params, "drive", 0.5), 0.0), 1.0)
    return [
        Distortion(drive_db=drive * 30.0),
        *_gain_from_mul(params),
    ]


def _highpass(params: Params) -> PluginList:
    return [
        HighpassFilter(cutoff_frequency_hz=_float_param(params, "freq", 50.0)),
        *_gain_from_mul(params),
    ]


def _lowpass(params: Params) -> PluginList:
    return [
        LowpassFilter(cutoff_frequency_hz=_float_param(params, "freq", 5000.0)),
        *_gain_from_mul(params),
    ]


def _biquad(params: Params) -> PluginList:
    biquad_type = int(_float_param(params, "type", 0.0))
    modes = {
        0: LadderFilter.Mode.LPF12,
        1: LadderFilter.Mode.HPF12,
        2: LadderFilter.Mode.BPF12,
    }
    if biquad_type not in modes:
        raise ValueError(
            f"Biquad type {biquad_type} non supporté par le moteur Pedalboard "
            "(types gérés : 0=LP, 1=HP, 2=BP)."
        )
    q = max(_float_param(params, "q", 0.707), 0.0)
    return [
        LadderFilter(
            mode=modes[biquad_type],
            cutoff_hz=_float_param(params, "freq", 1000.0),
            resonance=min(q / 20.0, 1.0),
        ),
        *_gain_from_mul(params),
    ]


def _chorus(params: Params) -> PluginList:
    # pyo exprime depth en ms ; Pedalboard attend une profondeur normalisée.
    depth_ms = _float_param(params, "depth", 1.5)
    return [
        Chorus(
            rate_hz=_float_param(params, "rate", 1.0),
            depth=min(max(depth_ms / 5.0, 0.0), 1.0),
            centre_delay_ms=7.0,
            feedback=_float_param(params, "feedback", 0.0),
            mix=_float_param(params, "bal", 0.5),
        ),
        *_gain_from_mul(params),
    ]


def _delay(params: Params) -> PluginList:
    # pyo Delay ne renvoie que le signal retardé : mix=1 reproduit ce comportement.
    return [
        Delay(
            delay_seconds=_float_param(params, "delay", 0.5),
            feedback=_float_param(params, "feedback", 0.0),
            mix=1.0,
        ),
        *_gain_from_mul(params),
    ]


def _reverb(params: Params) -> PluginList:
    wet = _float_param(params, "bal", 0.33)
    return [
        Reverb(
            room_size=_float_param(params, "size", 0.5),
            damping=_float_param(params, "damp", 0.5),
            wet_level=wet,
            dry_level=max(0.0, 1.0 - wet),
        ),
        *_gain_from_mul(params),
    ]


PYO_BUILDERS: dict[str, Callable[[Params], PluginList]] = {
    "pyo.lib.dynamics.Compress": _compress,
    "pyo.lib.dynamics.Gate": _gate,
    "pyo.lib.effects.Disto": _distortion,
    "pyo.lib.filters.ButHP": _highpass,
    "pyo.lib.filters.ButLP": _lowpass,
    "pyo.lib.filters.Biquad": _biquad,
    "pyo.lib.effects.Chorus": _chorus,
    "pyo.lib.effects.Delay": _delay,
    "pyo.lib.effects.Freeverb": _reverb,
    "pyo.lib.effects.Reverb": _reverb,
}


def _custom_delay(params: Params) -> PluginList:
    return [
        CustomDelay(
            delay_time=_float_param(
                params, "delay_time", _float_param(params, "delay", 0.5)
            ),
            feedback=_float_param(params, "feedback", 0.5),
            wet_level=_float_param(
                params, "wet_level", _float_param(params, "mix", 0.5)
            ),
        )
    ]


def _native_plugins(path: str, params: Params) -> PluginList:
    class_name = path.split(".", 1)[1]
    plugin_class = getattr(pedalboard, class_name, None)
    if (
        plugin_class is None
        or not isinstance(plugin_class, type)
        or not issubclass(plugin_class, pedalboard.Plugin)
    ):
        raise ValueError(f"Effet Pedalboard inconnu : {path}")

    clean_params = {key: value for key, value in params.items() if key != "mul"}
    plugin = plugin_class(**clean_params)
    return [plugin, *_gain_from_mul(params)]


def build_plugins(path: str, params: Params | None = None) -> PluginList:
    """Construit les plugins Pedalboard correspondant à un chemin d'effet."""
    clean_params = dict(params or {})

    if path == "libs.effect_lib.CustomDelay":
        return _custom_delay(clean_params)

    builder = PYO_BUILDERS.get(path)
    if builder is not None:
        return builder(clean_params)

    if path.startswith("pedalboard."):
        return _native_plugins(path, clean_params)

    raise ValueError(
        f"Effet non supporté par le moteur Pedalboard : {path}. "
        "Utilise un chemin pyo connu ou un chemin 'pedalboard.Classe'."
    )


def available_effects() -> list[str]:
    """Liste les chemins d'effets acceptés par le moteur."""
    native = [
        f"pedalboard.{name}"
        for name in dir(pedalboard)
        if isinstance(getattr(pedalboard, name, None), type)
        and issubclass(getattr(pedalboard, name), pedalboard.Plugin)
        and name != "Plugin"
    ]
    return sorted([*PYO_BUILDERS, "libs.effect_lib.CustomDelay", *native])
