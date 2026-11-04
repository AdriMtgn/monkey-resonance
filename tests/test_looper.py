"""Tests du looper (lecture d'un WAV mixé avec le signal live)."""

from __future__ import annotations

import numpy as np
import pytest
from libs import audio_stream as audio_stream_module
from libs.audio_stream import AudioStream, LoopPlayback
from pedalboard.io import AudioFile


class FakePlayback:
    """Remplace le stream de sortie : enregistre ce qui est écrit."""

    def __init__(self) -> None:
        self.blocks: list[np.ndarray] = []

    def write(self, audio: np.ndarray, sample_rate: float) -> None:
        self.blocks.append(np.array(audio, copy=True))


def make_playback(frames: int = 480, channels: int = 2) -> LoopPlayback:
    data = np.zeros((channels, frames), dtype=np.float32)
    data[:, : frames // 2] = 0.25
    return LoopPlayback("loop.wav", data, loop=True, volume=1.0)


def test_loop_wraps_and_keeps_position():
    loop = make_playback(frames=400)
    first = loop.next_block(256)
    assert first.shape == (2, 256)
    assert not loop.finished
    # 400 frames : le bloc suivant repart au début.
    second = loop.next_block(256)
    assert second.shape == (2, 256)
    assert loop.position == (256 - 400) + 256
    assert not loop.finished


def test_one_shot_finishes_and_returns_silence():
    loop = make_playback(frames=300)
    loop.loop = False
    block = loop.next_block(400)
    assert block.shape == (2, 400)
    assert loop.finished
    assert loop.next_block(128) is None


def test_loop_fades_in_and_out():
    loop = make_playback(frames=4800)
    data = loop._data
    assert abs(float(data[0, 0])) < 1e-6
    assert abs(float(data[0, -1])) < 1e-6
    # au milieu, le niveau du signal est conservé
    assert float(data[0, 1000]) == pytest.approx(0.25, abs=0.01)


def test_volume_is_applied():
    data = np.ones((2, 480), dtype=np.float32)
    loop = LoopPlayback("l.wav", data, volume=0.5)
    # le fondu de 5 ms atténue les bords, on lit au centre
    block = loop.next_block(480)[:, 240]
    assert float(block[0]) == pytest.approx(0.5, abs=1e-3)


def test_process_block_mixes_live_and_loop():
    engine = AudioStream(open_device=False)
    engine._running = True
    engine._loop = LoopPlayback(
        "l.wav", np.full((2, 480), 0.2, dtype=np.float32), loop=True, volume=1.0
    )
    sink = FakePlayback()
    segment = np.full((2, 128), 0.1, dtype=np.float32)

    engine._process_block(segment, sink)

    assert len(sink.blocks) == 1
    mixed = sink.blocks[0]
    assert mixed.shape == (2, 128)
    # live (0.1) + boucle (0.2), pondérée par le fondu du début
    expected = 0.1 + float(engine._loop._data[0, 64])
    assert float(mixed[0, 64]) == pytest.approx(expected, abs=1e-4)
    engine.close()


def test_process_block_does_not_advance_loop_without_playback():
    engine = AudioStream(open_device=False)
    engine._running = True
    sink = FakePlayback()
    engine._process_block(np.zeros((2, 128), dtype=np.float32), sink)
    assert engine.playback is None
    engine.close()


def test_engine_play_recording_requires_running_stream(tmp_path):
    wav = tmp_path / "x.wav"
    with AudioFile(str(wav), "w", samplerate=48000, num_channels=2) as f:
        f.write(np.zeros((2, 480), dtype=np.float32))

    engine = AudioStream(open_device=False)
    with pytest.raises(RuntimeError, match="not running"):
        engine.play_recording(str(wav))
    engine.close()


def test_engine_loads_wav_and_reports_status(tmp_path):
    wav = tmp_path / "boucle.wav"
    data = np.zeros((1, 960), dtype=np.float32)
    data[0, :480] = 0.3
    with AudioFile(str(wav), "w", samplerate=48000, num_channels=1) as f:
        f.write(data)

    engine = AudioStream(open_device=False)
    loop = engine._load_loop(str(wav), loop=True, volume=0.8)
    # une source mono est dupliquée sur les deux canaux
    assert loop._data.shape[0] == 2
    assert loop.duration_s == pytest.approx(960 / 48000)
    assert loop.descriptor()["volume"] == pytest.approx(0.8)
    engine.close()


def test_engine_rejects_missing_file(tmp_path):
    engine = AudioStream(open_device=False)
    engine._running = True
    with pytest.raises(FileNotFoundError):
        engine.play_recording(str(tmp_path / "absent.wav"))
    engine.close()


def test_stop_playback_reports_no_playback():
    engine = AudioStream(open_device=False)
    assert engine.stop_playback() is None
    assert engine.playback_status() is None
    engine.close()


# ----------------------------------------------------------------------
# Alimentation de l'analyse et de l'enregistrement par le moteur
# ----------------------------------------------------------------------
def test_listener_receives_dry_and_wet_per_block():
    engine = AudioStream(open_device=False)
    engine._running = True
    seen: list[tuple[np.ndarray, np.ndarray]] = []
    listener = lambda dry, wet: seen.append((dry.copy(), wet.copy()))  # noqa: E731
    engine.add_listener(listener)
    sink = FakePlayback()
    segment = np.full((2, 128), 0.1, dtype=np.float32)

    engine._process_block(segment, sink)

    assert len(seen) == 1
    dry, wet = seen[0]
    assert np.allclose(dry, segment)
    # volume 1.0 -> gain 0 dB : le wet est le dry après la chaîne (vide ici)
    assert np.allclose(wet, segment, atol=1e-6)
    engine.remove_listener(listener)
    engine.close()


def test_remove_listener_removes_bound_method():
    class Sink:
        def __init__(self) -> None:
            self.count = 0

        def on_audio(self, dry, wet) -> None:
            self.count += 1

    engine = AudioStream(open_device=False)
    engine._running = True
    sink = Sink()
    engine.add_listener(sink.on_audio)
    engine.remove_listener(sink.on_audio)

    engine._process_block(np.zeros((2, 128), dtype=np.float32), FakePlayback())

    assert sink.count == 0
    engine.close()


def test_recording_is_fed_by_engine(monkeypatch, tmp_path):
    monkeypatch.setattr(audio_stream_module, "records_folder", str(tmp_path))
    engine = AudioStream(open_device=False)
    engine._running = True
    sink = FakePlayback()

    path = engine.start_recording("tap.wav")
    for _ in range(4):
        engine._process_block(
            np.full((2, 128), 0.1, dtype=np.float32), sink
        )
    stopped = engine.stop_recording()

    assert stopped == path
    with AudioFile(path) as recorded:
        assert recorded.frames == 4 * 128
        assert recorded.num_channels == 2
    engine.close()
