"""Détection AudioBox / accès carte son avec le backend Pedalboard.

Les tests d'ouverture réelle sont désactivés par défaut : lancer avec
``RUN_AUDIO_TESTS=1`` quand l'AudioBox est libre.
"""

import os
import time

import pytest
from libs import audio_stream as audio_stream_module
from libs.audio_devices import list_devices, load_config
from libs.audio_stream import AudioStream
from pedalboard.io import AudioFile


def _has_audiobox() -> bool:
    inputs, _outputs = list_devices()
    return any("audiobox" in str(device["name"]).lower() for device in inputs.values())


def test_pedalboard_lists_audio_devices():
    inputs, outputs = list_devices()
    if not inputs and not outputs:
        pytest.skip("Aucun périphérique audio détecté dans cet environnement")
    assert all("name" in device for device in inputs.values())
    assert all("name" in device for device in outputs.values())


def test_audiobox_is_detected():
    if not _has_audiobox():
        pytest.skip("AudioBox USB 96 absente")
    inputs, _ = list_devices()
    names = [str(device["name"]) for device in inputs.values()]
    assert any("AudioBox USB 96" in name for name in names)


def test_config_prefers_direct_hardware_for_low_latency():
    if not _has_audiobox():
        pytest.skip("AudioBox USB 96 absente")
    config = load_config()
    assert "AudioBox" in config.input_device
    assert "AudioBox" in config.output_device
    # Entrée et sortie sur le chemin matériel direct, sans couche
    # PipeWire/Pulse ni période dsnoop (1024 frames).
    assert "Direct hardware device" in config.input_device
    assert "Direct hardware device" in config.output_device
    assert config.record_device == config.input_device
    assert config.buffer_latency_ms > 0


@pytest.mark.skipif(
    os.environ.get("RUN_AUDIO_TESTS") != "1",
    reason="RUN_AUDIO_TESTS=1 requis (ouvre réellement l'AudioBox)",
)
def test_live_stream_opens_muted():
    config = load_config()
    engine = AudioStream(
        input_device=config.input_device,
        output_device=config.output_device,
        sample_rate=config.sample_rate,
        buffer_size=config.buffer_size,
        num_input_channels=config.input_channels,
        num_output_channels=config.output_channels,
        start_muted=True,
    )
    try:
        engine.start(unmute=False)
        assert engine.is_running
        assert engine.buffer_size > 0
        assert engine.sample_rate > 0
        time.sleep(0.5)
        engine.read_available()
    finally:
        engine.close()


@pytest.mark.skipif(
    os.environ.get("RUN_AUDIO_TESTS") != "1",
    reason="RUN_AUDIO_TESTS=1 requis (ouvre réellement l'AudioBox)",
)
def test_live_recording_is_tapped_from_engine(monkeypatch, tmp_path):
    """L'enregistrement est alimenté par le moteur, sans capture secondaire."""
    config = load_config()
    monkeypatch.setattr(audio_stream_module, "records_folder", str(tmp_path))
    engine = AudioStream(
        input_device=config.input_device,
        output_device=config.output_device,
        sample_rate=config.sample_rate,
        buffer_size=config.buffer_size,
        num_input_channels=config.input_channels,
        num_output_channels=config.output_channels,
        start_muted=True,
    )
    try:
        engine.start(unmute=False)
        engine.start_recording("live_test.wav")
        time.sleep(1.0)
        path = engine.stop_recording()
        assert path is not None
        assert engine.recording is False
        with AudioFile(path) as recorded:
            assert recorded.samplerate == config.sample_rate
            assert recorded.num_channels == config.input_channels
            assert recorded.frames >= config.sample_rate // 2
    finally:
        engine.close()
