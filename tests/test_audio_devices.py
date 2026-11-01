"""Tests purs de la résolution des périphériques audio (sans ouvrir la carte)."""

import pytest
from libs.audio_devices import AudioConfig, resolve_device_name


def _devices():
    return {
        0: {
            "index": 0,
            "name": "Default Audio Device (1)",
            "kind": "input",
            "default": True,
            "direct_hardware": False,
        },
        1: {
            "index": 1,
            "name": "AudioBox USB 96, USB Audio; Front output / input",
            "kind": "input",
            "default": False,
            "direct_hardware": False,
        },
        2: {
            "index": 2,
            "name": (
                "AudioBox USB 96, USB Audio; "
                "Direct hardware device without any conversions"
            ),
            "kind": "input",
            "default": False,
            "direct_hardware": True,
        },
        3: {
            "index": 3,
            "name": "AudioBox USB 96, USB Audio; Direct sample snooping device",
            "kind": "input",
            "default": False,
            "direct_hardware": False,
        },
    }


def test_resolve_by_index():
    assert resolve_device_name(2, _devices(), "input").endswith("without any conversions")


def test_resolve_by_numeric_string_index():
    resolved = resolve_device_name("2", _devices(), "input")
    assert resolved.endswith("without any conversions")


def test_resolve_by_exact_name():
    name = "Default Audio Device (1)"
    assert resolve_device_name(name, _devices(), "input") == name


def test_resolve_by_substring_prefers_direct_hardware():
    resolved = resolve_device_name("audiobox", _devices(), "input")
    assert "Direct hardware device" in resolved


def test_resolve_auto_prefers_audiobox_direct_hardware():
    resolved = resolve_device_name(None, _devices(), "input")
    assert "AudioBox" in resolved
    assert "Direct hardware device" in resolved


def test_resolve_auto_prefers_shared_capture_when_requested():
    resolved = resolve_device_name(
        None, _devices(), "input", prefer_shared_capture=True
    )
    assert "AudioBox" in resolved
    assert "Direct sample snooping device" in resolved


def test_resolve_substring_upgrades_to_shared_capture():
    resolved = resolve_device_name(
        "audiobox", _devices(), "input", prefer_shared_capture=True
    )
    assert "Direct sample snooping device" in resolved


def test_resolve_exact_name_is_never_upgraded():
    exact = "AudioBox USB 96, USB Audio; Direct hardware device without any conversions"
    resolved = resolve_device_name(
        exact, _devices(), "input", prefer_shared_capture=True
    )
    assert resolved == exact


def test_resolve_unknown_raises_with_available_devices():
    with pytest.raises(ValueError, match="Disponibles"):
        resolve_device_name("does-not-exist", _devices(), "input")


def test_resolve_empty_raises():
    with pytest.raises(RuntimeError, match="/dev/snd"):
        resolve_device_name(None, {}, "input")


def test_audio_config_latency():
    config = AudioConfig(
        input_device="in",
        output_device="out",
        sample_rate=48000,
        buffer_size=256,
    )
    assert config.buffer_latency_ms == pytest.approx(5.333, rel=1e-3)
    assert config.round_trip_latency_ms == pytest.approx(10.667, rel=1e-3)
