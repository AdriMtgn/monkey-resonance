"""Tests de l'analyseur audio (numpy, sans périphérique)."""

import numpy as np
import pytest
from libs.music_analysis import (
    AudioAnalyzer,
    detect_pitch,
    midi_note,
    note_name,
)


class FakeStream:
    """Faux AudioStream : l'analyseur ne fait que lire ses métadonnées."""

    sample_rate = 48000.0
    num_input_channels = 2
    record_device = "fake-dsnoop"


def make_analyzer(**kwargs) -> AudioAnalyzer:
    return AudioAnalyzer(FakeStream(), open_capture=False, **kwargs)


def sine(frequency: float = 440.0, amplitude: float = 0.5, seconds: float = 0.2):
    sample_rate = FakeStream.sample_rate
    time = np.arange(int(sample_rate * seconds)) / sample_rate
    signal = (amplitude * np.sin(2.0 * np.pi * frequency * time)).astype(np.float32)
    return np.vstack([signal, signal])


def test_midi_note_and_name():
    assert midi_note(440.0) == 69
    assert note_name(69) == "A4"
    assert midi_note(261.63) == 60
    assert note_name(60) == "C4"
    assert midi_note(0) is None
    assert note_name(None) is None


def test_detect_pitch_sine():
    frequency, confidence = detect_pitch(sine(440.0)[0], 48000.0)
    assert frequency == pytest.approx(440.0, abs=1.0)
    assert confidence > 0.8


def test_detect_pitch_silence():
    frequency, confidence = detect_pitch(np.zeros(4800, dtype=np.float32), 48000.0)
    assert frequency is None
    assert confidence == 0.0


def test_analyze_rms_level():
    analyzer = make_analyzer()
    analyzer.feed(sine(amplitude=0.5))

    result = analyzer.analyze_rms(0, window_size=4800)
    assert result["active"] is True
    assert result["signal"] is True
    # RMS d'une sinusoïde d'amplitude 0.5 = 0.5 / sqrt(2)
    assert result["rms_level"] == pytest.approx(0.3536, abs=0.01)
    assert result["rms_db"] == pytest.approx(-9.0, abs=0.3)


def test_analyze_pitch_and_profile():
    analyzer = make_analyzer()
    analyzer.feed(sine(440.0))

    pitch = analyzer.analyze_pitch(0)
    assert pitch["frequency_hz"] == pytest.approx(440.0, abs=1.0)
    assert pitch["midi_note"] == 69
    assert pitch["note_name"] == "A4"
    assert pitch["confidence"] > 0.8

    profile = analyzer.analyze_audio_profile(0)
    assert profile["active"] is True
    assert profile["signal"] is True
    assert profile["midi_note"] == 69
    assert profile["note_name"] == "A4"
    assert profile["pitch"] == pytest.approx(440.0, abs=1.0)


def test_analyze_frequency():
    analyzer = make_analyzer()
    analyzer.feed(sine(440.0))

    result = analyzer.analyze_frequency(0, fft_size=8192)
    assert result["dominant_frequency_hz"] == pytest.approx(440.0, abs=6.0)
    assert result["spectral_centroid_hz"] == pytest.approx(440.0, abs=20.0)
    assert result["signal"] is True
    assert result["peaks"]
    assert max(result["bands"].values()) > 0.5


def test_silence_has_no_signal():
    analyzer = make_analyzer()
    analyzer.feed(np.zeros((2, 9600), dtype=np.float32))

    rms = analyzer.analyze_rms(0)
    assert rms["signal"] is False
    assert rms["rms_level"] == pytest.approx(0.0)

    pitch = analyzer.analyze_pitch(0)
    assert pitch["frequency_hz"] is None
    assert pitch["midi_note"] is None

    frequency = analyzer.analyze_frequency(0)
    assert frequency["signal"] is False
    assert frequency["dominant_frequency_hz"] is None


def test_faint_noise_is_not_signal():
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal((2, 9600)) * 3e-4).astype(np.float32)
    analyzer = make_analyzer()
    analyzer.feed(noise)

    assert analyzer.analyze_rms(0)["signal"] is False
    assert analyzer.analyze_pitch(0)["signal"] is False
    assert analyzer.analyze_frequency(0)["signal"] is False


def test_index_and_state_errors():
    analyzer = make_analyzer()
    assert analyzer.analyze_rms(0)["active"] is True

    analyzer.feed(sine(440.0, seconds=0.05))
    assert analyzer.analyze_rms(2)["active"] is False
    assert "hors plage" in analyzer.analyze_rms(2)["error"]

    analyzer.close()
    result = analyzer.analyze_rms(0)
    assert result["active"] is False
    assert "non démarrée" in result["error"]


def test_feed_channel_validation():
    analyzer = make_analyzer()
    with pytest.raises(ValueError, match="2 canaux"):
        analyzer.feed(np.zeros((1, 128), dtype=np.float32))


def test_ring_buffer_keeps_latest_frames():
    analyzer = make_analyzer(ring_seconds=0.1)  # 4800 frames à 48 kHz
    ramp = np.arange(10000, dtype=np.float32)
    analyzer.feed(np.vstack([ramp, ramp]))

    latest = analyzer.latest(4800)
    assert latest.shape == (2, 4800)
    assert latest[0, 0] == pytest.approx(5200.0)
    assert latest[0, -1] == pytest.approx(9999.0)


def test_latest_pads_with_zeros():
    analyzer = make_analyzer()
    analyzer.feed(np.ones((2, 100), dtype=np.float32))

    latest = analyzer.latest(500)
    assert latest.shape == (2, 500)
    assert np.all(latest[:, :400] == 0.0)
    assert np.all(latest[:, 400:] == 1.0)
