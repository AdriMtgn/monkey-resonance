"""Tests du moteur multi-pistes et du mixeur global (sans périphérique)."""

from __future__ import annotations

import numpy as np
import pytest
from libs.audio_devices import AudioConfig
from libs.mixer import (
    MixerEngine,
    parse_input_layout,
    parse_output_layout,
)


class FakePlayback:
    """Remplace le stream de sortie : enregistre ce qui est écrit."""

    def __init__(self) -> None:
        self.blocks: list[np.ndarray] = []

    def write(self, audio: np.ndarray, sample_rate: float) -> None:
        self.blocks.append(np.array(audio, copy=True))


def make_config(
    *,
    input_channels: int = 2,
    output_channels: int = 2,
    input_layout: str = "",
    output_layout: str = "",
    start_muted: bool = False,
) -> AudioConfig:
    return AudioConfig(
        input_device="fake-in",
        output_device="fake-out",
        input_channels=input_channels,
        output_channels=output_channels,
        input_layout=input_layout,
        output_layout=output_layout,
        start_muted=start_muted,
    )


def make_engine(**kwargs) -> MixerEngine:
    return MixerEngine(make_config(**kwargs), open_device=False)


def process(engine: MixerEngine, segment: np.ndarray) -> np.ndarray:
    sink = FakePlayback()
    engine._process_block(segment, sink)
    assert len(sink.blocks) == 1
    return sink.blocks[0]


def test_default_input_layout_is_one_mono_per_channel():
    specs = parse_input_layout(None, 2)
    assert [spec.name for spec in specs] == ["input_0", "input_1"]
    assert [spec.channels for spec in specs] == [(0,), (1,)]


def test_explicit_input_layout():
    specs = parse_input_layout("bass:0;keys:0,1", 2)
    assert [spec.name for spec in specs] == ["bass", "keys"]
    assert [spec.channels for spec in specs] == [(0,), (0, 1)]


def test_invalid_input_layout():
    with pytest.raises(ValueError, match="hors plage"):
        parse_input_layout("bass:3", 2)
    with pytest.raises(ValueError, match="dupliqué"):
        parse_input_layout("bass:0;bass:1", 2)
    with pytest.raises(ValueError, match="format"):
        parse_input_layout("bass", 2)


def test_default_output_layout_is_main_stereo():
    specs = parse_output_layout(None, 2)
    assert specs[0].name == "main"
    assert (specs[0].left_channel, specs[0].right_channel) == (0, 1)


def test_explicit_output_layout():
    specs = parse_output_layout("main:0,1;cue:2,3", 4)
    assert [spec.name for spec in specs] == ["main", "cue"]
    assert (specs[1].left_channel, specs[1].right_channel) == (2, 3)


def test_default_engine_splits_inputs_and_routes_to_main():
    engine = make_engine()
    assert len(engine.inputs) == 2
    assert [track.input_channels for track in engine.inputs] == [(0,), (1,)]
    assert len(engine.outputs) == 1

    state = engine.get_mixer_state()
    assert state["inputs"][0]["routes"] == {"0": 1.0}
    assert state["inputs"][1]["routes"] == {"0": 1.0}
    assert state["outputs"][0]["name"] == "main"
    engine.close()


def test_independent_inputs_are_mixed_into_main():
    engine = make_engine()
    segment = np.zeros((2, 128), dtype=np.float32)
    segment[0, :] = 0.1
    segment[1, :] = 0.2

    mixed = process(engine, segment)
    assert mixed.shape == (2, 128)
    assert float(mixed[0, 64]) == pytest.approx(0.3, abs=1e-6)
    assert float(mixed[1, 64]) == pytest.approx(0.3, abs=1e-6)
    engine.close()


def test_input_volume_and_route_volume_are_independent():
    engine = make_engine()
    segment = np.zeros((2, 128), dtype=np.float32)
    segment[0, :] = 0.1
    segment[1, :] = 0.2

    engine.set_route(0, 0, 0.5)
    mixed = process(engine, segment)
    assert float(mixed[0, 64]) == pytest.approx(0.05 + 0.2, abs=1e-6)

    engine.set_input_mix(1, volume=0.5)
    mixed = process(engine, segment)
    assert float(mixed[0, 64]) == pytest.approx(0.05 + 0.1, abs=1e-6)
    engine.close()


def test_balance_moves_input_between_left_and_right():
    engine = make_engine()
    segment = np.zeros((2, 128), dtype=np.float32)
    segment[0, :] = 0.1
    segment[1, :] = 0.2

    engine.set_input_mix(0, balance=-1.0)
    mixed = process(engine, segment)
    assert float(mixed[0, 64]) == pytest.approx(0.3, abs=1e-6)
    assert float(mixed[1, 64]) == pytest.approx(0.2, abs=1e-6)

    engine.set_input_mix(0, balance=1.0)
    mixed = process(engine, segment)
    assert float(mixed[0, 64]) == pytest.approx(0.2, abs=1e-6)
    assert float(mixed[1, 64]) == pytest.approx(0.3, abs=1e-6)
    engine.close()


def test_left_and_right_gains_are_independent():
    engine = make_engine()
    segment = np.zeros((2, 128), dtype=np.float32)
    segment[0, :] = 0.1
    segment[1, :] = 0.2

    engine.set_input_mix(0, left_gain=2.0, right_gain=0.5)
    mixed = process(engine, segment)
    assert float(mixed[0, 64]) == pytest.approx(0.2 + 0.2, abs=1e-6)
    assert float(mixed[1, 64]) == pytest.approx(0.05 + 0.2, abs=1e-6)
    engine.close()


def test_second_output_bus_receives_its_own_route():
    engine = make_engine(output_channels=4)
    engine.add_output("cue", 2, 3)
    segment = np.zeros((2, 128), dtype=np.float32)
    segment[0, :] = 0.1
    segment[1, :] = 0.2

    # Par défaut, le nouveau bus ne reçoit rien.
    mixed = process(engine, segment)
    assert float(mixed[2, 64]) == pytest.approx(0.0)
    assert float(mixed[3, 64]) == pytest.approx(0.0)

    engine.set_route(0, 1, 0.5)
    mixed = process(engine, segment)
    assert float(mixed[0, 64]) == pytest.approx(0.3, abs=1e-6)
    assert float(mixed[2, 64]) == pytest.approx(0.05, abs=1e-6)
    assert float(mixed[3, 64]) == pytest.approx(0.05, abs=1e-6)
    engine.close()


def test_output_volume_mute_and_master_volume():
    engine = make_engine()
    segment = np.zeros((2, 128), dtype=np.float32)
    segment[0, :] = 0.1
    segment[1, :] = 0.2

    engine.set_output_volume(0, 0.5)
    mixed = process(engine, segment)
    assert float(mixed[0, 64]) == pytest.approx(0.15, abs=1e-6)

    engine.mute_output(0)
    mixed = process(engine, segment)
    assert float(mixed[0, 64]) == pytest.approx(0.0)

    engine.unmute_output(0)
    engine.set_master_volume(0.5)
    mixed = process(engine, segment)
    assert float(mixed[0, 64]) == pytest.approx(0.075, abs=1e-6)
    engine.close()


def test_add_remove_input_and_change_channels():
    engine = make_engine()
    added = engine.add_input("keys", [0, 1])
    assert added["index"] == 2
    assert engine.inputs[2].input_channels == (0, 1)

    engine.set_input_channels(2, [1])
    assert engine.inputs[2].input_channels == (1,)

    removed = engine.remove_input(2)
    assert removed["result"] == "input_removed"
    assert len(engine.inputs) == 2
    engine.close()


def test_add_remove_output_remaps_routes():
    engine = make_engine(output_channels=4)
    engine.add_output("cue", 2, 3)
    engine.set_route(0, 1, 0.7)
    engine.set_route(1, 1, 0.4)

    removed = engine.remove_output(1)
    assert removed["result"] == "output_removed"
    assert len(engine.outputs) == 1
    state = engine.get_mixer_state()
    assert state["inputs"][0]["routes"] == {"0": 1.0}
    assert state["inputs"][1]["routes"] == {"0": 1.0}
    engine.close()


def test_start_muted_is_per_input_and_master_mute_is_global():
    engine = MixerEngine(make_config(start_muted=True), open_device=False)
    assert all(track._muted for track in engine.inputs)

    segment = np.zeros((2, 128), dtype=np.float32)
    segment[0, :] = 0.1
    segment[1, :] = 0.2
    mixed = process(engine, segment)
    assert float(mixed[0, 64]) == pytest.approx(0.0)

    # Unmute la piste 0 uniquement : la piste 1 reste muette.
    engine.inputs[0].start()
    mixed = process(engine, segment)
    assert float(mixed[0, 64]) == pytest.approx(0.1, abs=1e-6)

    # Le mute master coupe tout, indépendamment des pistes.
    engine.mute()
    mixed = process(engine, segment)
    assert float(mixed[0, 64]) == pytest.approx(0.0)
    engine.unmute()
    mixed = process(engine, segment)
    assert float(mixed[0, 64]) == pytest.approx(0.1, abs=1e-6)
    engine.close()


def test_latency_has_no_extra_buffer():
    engine = make_engine()
    expected = (engine.capture_block_size + engine.buffer_size) / engine.sample_rate * 1000.0
    assert engine.latency_ms == pytest.approx(expected)
    engine.close()


def test_stereo_input_track_keeps_left_right():
    engine = make_engine(input_layout="keys:0,1")
    segment = np.zeros((2, 128), dtype=np.float32)
    segment[0, :] = 0.1
    segment[1, :] = 0.2

    mixed = process(engine, segment)
    assert float(mixed[0, 64]) == pytest.approx(0.1, abs=1e-6)
    assert float(mixed[1, 64]) == pytest.approx(0.2, abs=1e-6)
    engine.close()
