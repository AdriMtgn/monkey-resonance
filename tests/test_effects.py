"""Tests du catalogue d'effets pyo -> Pedalboard (sans device audio)."""

import numpy as np
import pytest
from libs.effect_lib import (
    CustomDelay,
    EffectSlot,
    available_effects,
    build_plugins,
)
from pedalboard import (
    Chorus,
    Compressor,
    Distortion,
    Gain,
    HighpassFilter,
    LadderFilter,
    LowpassFilter,
    NoiseGate,
    Pedalboard,
)


def test_compress_maps_pyo_params():
    plugins = build_plugins(
        "pyo.lib.dynamics.Compress",
        {"thresh": -30, "ratio": 4, "risetime": 0.01, "falltime": 0.05, "mul": 1.2},
    )
    compressor = plugins[0]
    assert isinstance(compressor, Compressor)
    assert compressor.threshold_db == pytest.approx(-30)
    assert compressor.ratio == pytest.approx(4)
    assert compressor.attack_ms == pytest.approx(10)
    assert compressor.release_ms == pytest.approx(50)
    assert isinstance(plugins[1], Gain)


def test_gate_distortion_filters_and_chorus():
    assert isinstance(
        build_plugins("pyo.lib.dynamics.Gate", {"thresh": -70, "risetime": 0.001})[0],
        NoiseGate,
    )
    assert isinstance(
        build_plugins("pyo.lib.effects.Disto", {"drive": 0.5})[0], Distortion
    )
    assert isinstance(
        build_plugins("pyo.lib.filters.ButHP", {"freq": 120})[0], HighpassFilter
    )
    assert isinstance(
        build_plugins("pyo.lib.filters.ButLP", {"freq": 7000})[0], LowpassFilter
    )
    assert isinstance(
        build_plugins("pyo.lib.filters.Biquad", {"freq": 3000, "q": 10, "type": 2})[0],
        LadderFilter,
    )
    assert isinstance(
        build_plugins("pyo.lib.effects.Chorus", {"depth": 1.5, "bal": 0.5})[0],
        Chorus,
    )


def test_native_pedalboard_path_with_mul():
    plugins = build_plugins("pedalboard.Gain", {"gain_db": -3, "mul": 2})
    assert isinstance(plugins[0], Gain)
    assert plugins[0].gain_db == pytest.approx(-3)
    assert plugins[1].gain_db == pytest.approx(6.0206, rel=1e-3)


def test_custom_delay_keeps_legacy_api():
    delay = CustomDelay(delay_time=0.3, feedback=0.4, wet_level=0.6)
    assert delay.delay_seconds == pytest.approx(0.3)
    delay.setDelayTime(0.1)
    delay.setFeedback(0.2)
    delay.setWetLevel(0.3)
    assert delay.getDelayTime() == pytest.approx(0.1)
    assert delay.getFeedback() == pytest.approx(0.2)
    assert delay.getWetLevel() == pytest.approx(0.3)


def test_custom_delay_path():
    plugins = build_plugins(
        "libs.effect_lib.CustomDelay",
        {"delay_time": 0.2, "feedback": 0.3, "wet_level": 0.4},
    )
    assert isinstance(plugins[0], CustomDelay)


def test_effect_slot_roundtrip_and_processing():
    slot = EffectSlot.create("pyo.lib.effects.Disto", {"drive": 0.5, "mul": 0.7})
    assert slot.descriptor()["effect"] == "pyo.lib.effects.Disto"
    assert slot.descriptor()["params"]["drive"] == 0.5
    assert len(slot.plugins) == 2

    audio = np.zeros((2, 4800), dtype=np.float32)
    processed = Pedalboard(slot.plugins)(audio, 48000)
    assert processed.shape == audio.shape


def test_unknown_effect_raises():
    with pytest.raises(ValueError, match="non supporté"):
        build_plugins("pyo.lib.unknown.Nope", {})


def test_available_effects_contains_pyo_and_native():
    effects = available_effects()
    assert "pyo.lib.effects.Chorus" in effects
    assert "pedalboard.Chorus" in effects
