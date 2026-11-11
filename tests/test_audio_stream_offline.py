"""Tests de la chaîne Pedalboard sans ouvrir de périphérique audio."""

import json

import pytest
from libs import audio_stream as audio_stream_module
from libs.audio_stream import AudioStream
from pedalboard import Compressor, Gain


@pytest.fixture
def engine():
    instance = AudioStream(open_device=False)
    yield instance
    instance.close()


def test_add_update_remove_effect(engine):
    engine.add_effect(None, "pyo.lib.dynamics.Compress", thresh=-30, ratio=4)
    assert len(engine.effects_chain) == 1
    assert engine.effects_chain[0]["effect"] == "pyo.lib.dynamics.Compress"

    engine.update_effect(0, thresh=-12)
    compressor = engine._slots[0].plugins[0]
    assert isinstance(compressor, Compressor)
    assert compressor.threshold_db == pytest.approx(-12)
    assert engine.effects_chain[0]["params"]["thresh"] == -12

    engine.add_effect(0, "pedalboard.Gain", gain_db=-3)
    assert len(engine.effects_chain) == 2
    assert engine.effects_chain[0]["effect"] == "pedalboard.Gain"

    engine.remove_effect(0)
    assert len(engine.effects_chain) == 1
    assert engine.effects_chain[0]["effect"] == "pyo.lib.dynamics.Compress"


def test_invalid_positions(engine):
    with pytest.raises(IndexError):
        engine.add_effect(1, "pedalboard.Gain")
    with pytest.raises(IndexError):
        engine.remove_effect(0)
    with pytest.raises(IndexError):
        engine.update_effect(None, gain_db=0)
    with pytest.raises(IndexError):
        engine.update_effect(0, gain_db=0)


def test_global_volume_and_mute(engine):
    engine.global_volume = 0.5
    assert engine.global_volume == pytest.approx(0.5)
    engine.mute()
    assert engine._muted is True
    engine.global_volume = 0.25
    assert engine.global_volume == pytest.approx(0.25)


def test_save_and_load_effects(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(audio_stream_module, "effects_folder", str(tmp_path))
    engine.add_effect(None, "pyo.lib.filters.ButHP", freq=120)
    engine.global_volume = 0.8

    path = engine.save_effects("test_chain")
    with open(path, encoding="utf-8") as saved_file:
        saved = json.load(saved_file)
    assert saved["engine"] == "pedalboard"
    assert saved["global_volume"] == pytest.approx(0.8)
    assert saved["effect_chain"][0]["effect"] == "pyo.lib.filters.ButHP"

    other = AudioStream(open_device=False)
    other.load_effects("test_chain")
    assert other.effects_chain == engine.effects_chain
    assert other.global_volume == pytest.approx(0.8)
    other.close()


def test_load_legacy_list_format(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(audio_stream_module, "effects_folder", str(tmp_path))
    legacy = [{"effect": "pedalboard.Gain", "params": {"gain_db": -6}}]
    (tmp_path / "legacy.json").write_text(json.dumps(legacy), encoding="utf-8")

    engine.load_effects("legacy")
    assert engine.effects_chain == [
        {**legacy[0], "enabled": True},
    ]
    assert engine.global_volume == pytest.approx(1.0)


def test_effect_bypass_is_not_processed(engine):
    engine.add_effect(None, "pedalboard.Gain", gain_db=-3)
    engine.set_effect_enabled(0, False)
    assert engine.effects_chain[0]["enabled"] is False
    assert len(engine._board) == 1  # gain de sortie uniquement
    engine.set_effect_enabled(0, True)
    assert len(engine._board) == 2


def test_load_unknown_effect_keeps_previous_chain(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(audio_stream_module, "effects_folder", str(tmp_path))
    engine.add_effect(None, "pedalboard.Gain", gain_db=-3)
    (tmp_path / "bad.json").write_text(
        json.dumps(
            {
                "effect_chain": [
                    {"effect": "pyo.lib.unknown.Nope", "params": {}},
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="non supporté"):
        engine.load_effects("bad")
    assert len(engine.effects_chain) == 1


def test_string_representation(engine):
    text = str(engine)
    assert "AudioStream" in text
    assert "stopped" in text
    assert "effects=0" in text


def test_recording_requires_running_stream(engine):
    with pytest.raises(RuntimeError, match="not running"):
        engine.start_recording("nope.wav")
    with pytest.raises(RuntimeError, match="No recording"):
        engine.stop_recording()


def test_output_gain_is_always_last(engine):
    engine.add_effect(None, "pedalboard.Gain", gain_db=-3)
    plugins = engine._board
    assert isinstance(plugins[-1], Gain)
