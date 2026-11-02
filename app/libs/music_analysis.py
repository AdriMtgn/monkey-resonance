"""Analyse audio temps réel pour le moteur Pedalboard.

Le callback C++ de ``pedalboard.io.AudioStream`` n'expose pas ses échantillons
à Python. Comme pour l'enregistrement, on ouvre donc une **capture dsnoop
dédiée** (input-only) qui alimente un ring buffer numpy. Les outils MCP lisent
ce buffer sans jamais toucher au thread audio.

L'analyse est purement numpy : RMS, pitch (autocorrélation), spectre FFT,
profil MIDI. Aucune dépendance à pyo.
"""

from __future__ import annotations

import atexit
import logging
import math
import sys
import threading
import time
from typing import Any

import numpy as np
from pedalboard.io import AudioStream as PedalboardAudioStream

logger = logging.getLogger(__name__)

# ~4 s à 48 kHz : assez long pour détecter des fondamentales autour de 50 Hz.
RING_SECONDS = 4.0
CAPTURE_BUFFER_SIZE = 2048
CAPTURE_POLL_S = 0.004
# Seuil « signal présent » (~-60 dBFS) : sous ce niveau, on considère que
# c'est le bruit de fond de l'interface, pas un instrument.
SILENCE_RMS = 1e-3

_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


class AudioAnalysisError(RuntimeError):
    """Impossible d'ouvrir ou de lire la capture d'analyse."""


def _db(value: float) -> float:
    return 20.0 * math.log10(max(float(value), 1e-12))


def midi_note(frequency_hz: float | None) -> int | None:
    """Convertit une fréquence en numéro MIDI (None si fréquence invalide)."""
    if not frequency_hz or frequency_hz <= 0:
        return None
    return round(69 + 12 * math.log2(frequency_hz / 440.0))


def note_name(midi: int | None) -> str | None:
    """Nom de note (``A4``, ``C#3``…) pour un numéro MIDI."""
    if midi is None:
        return None
    return f"{_NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def detect_pitch(
    samples: np.ndarray,
    sample_rate: float,
    *,
    fmin: float = 50.0,
    fmax: float = 2000.0,
    silence_rms: float = SILENCE_RMS,
) -> tuple[float | None, float]:
    """Détecte la fondamentale par autocorrélation normalisée.

    Retourne ``(fréquence_hz, confiance)``. ``(None, 0.0)`` si le signal est
    trop faible ou pas périodique.
    """
    data = np.asarray(samples, dtype=np.float64)
    if data.size < 2:
        return None, 0.0

    data = data - data.mean()
    rms = float(np.sqrt(np.mean(data * data)))
    if rms < silence_rms:
        return None, 0.0

    n = data.size
    min_lag = max(int(sample_rate / fmax), 1)
    max_lag = min(int(sample_rate / fmin), n - 1)
    if max_lag <= min_lag:
        return None, 0.0

    # Autocorrélation via FFT (plus rapide que O(n²) sur 100 ms).
    size = 1 << (2 * n - 1).bit_length()
    spectrum = np.fft.rfft(data, size)
    corr = np.fft.irfft(spectrum * np.conj(spectrum), size)[:n]
    corr /= np.maximum(corr[0], 1e-12)

    window = corr[min_lag:max_lag]
    peak = int(np.argmax(window)) + min_lag
    confidence = float(corr[peak])
    if confidence <= 0.2:
        return None, max(confidence, 0.0)

    # Interpolation parabolique pour affiner la période.
    if 0 < peak < n - 1:
        left, center, right = corr[peak - 1], corr[peak], corr[peak + 1]
        denominator = left - 2.0 * center + right
        if abs(denominator) > 1e-12:
            peak = peak + 0.5 * (left - right) / denominator

    frequency = sample_rate / peak
    if not fmin <= frequency <= fmax:
        return None, confidence
    return float(frequency), confidence


class AudioAnalyzer:
    """Analyse l'entrée d'un ``AudioStream`` via une capture dsnoop dédiée."""

    def __init__(
        self,
        audio_stream: Any,
        *,
        open_capture: bool = True,
        ring_seconds: float = RING_SECONDS,
    ) -> None:
        self._stream = audio_stream
        self._sample_rate = float(audio_stream.sample_rate)
        self._channels = int(audio_stream.num_input_channels)
        self._ring_size = max(int(self._sample_rate * ring_seconds), 4096)
        self._ring = np.zeros((self._channels, self._ring_size), dtype=np.float32)
        self._write = 0
        self._count = 0
        self._data_lock = threading.Lock()

        self._capture: PedalboardAudioStream | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        # Mode hors-ligne (tests) : les échantillons sont fournis via feed().
        self._offline = not open_capture
        self._lifecycle_lock = threading.Lock()
        self._error: str | None = None

        if open_capture:
            self.start()

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._running

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def sample_rate(self) -> float:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    def start(self) -> None:
        """Ouvre la capture d'analyse et démarre le thread de lecture."""
        with self._lifecycle_lock:
            if self._running:
                return
            record_device = getattr(self._stream, "record_device", None)
            try:
                capture = PedalboardAudioStream(
                    input_device_name=record_device,
                    output_device_name=None,
                    plugins=None,
                    sample_rate=self._sample_rate,
                    buffer_size=CAPTURE_BUFFER_SIZE,
                    num_input_channels=self._channels,
                    num_output_channels=0,
                )
                capture.ignore_dropped_input = True
                capture.__enter__()
            except (RuntimeError, ValueError, OSError) as exc:
                self._error = (
                    "Impossible d'ouvrir la capture d'analyse sur "
                    f"{record_device!r} : {exc}. L'entrée doit être un device "
                    "partageable (dsnoop)."
                )
                logger.warning(self._error)
                raise AudioAnalysisError(self._error) from exc

            self._capture = capture
            self._error = None
            self._running = True
            self._thread = threading.Thread(
                target=self._capture_loop,
                name="pedalboard-analysis",
                daemon=True,
            )
            self._thread.start()
            atexit.register(self.close)
            logger.info(
                "Analyse audio démarrée : in=%r sr=%g canaux=%s",
                record_device,
                self._sample_rate,
                self._channels,
            )

    def _capture_loop(self) -> None:
        while self._running:
            capture = self._capture
            if capture is None:
                break
            try:
                chunk = capture.read(0)
            except (RuntimeError, ValueError, OSError) as exc:
                self._error = f"Lecture de la capture d'analyse échouée : {exc}"
                logger.exception(self._error)
                self._running = False
                break
            if chunk.size:
                self.feed(chunk)
            else:
                time.sleep(CAPTURE_POLL_S)

    def close(self) -> None:
        """Arrête le thread d'analyse et ferme la capture."""
        with self._lifecycle_lock:
            if not self._running and self._capture is None and not self._offline:
                return
            self._running = False
            thread = self._thread
            self._thread = None
            capture = self._capture
            self._capture = None
            self._offline = False

        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        if capture is not None and capture.running:
            try:
                capture.__exit__(None, None, None)
            except (RuntimeError, ValueError, OSError):
                logger.debug("Fermeture de la capture d'analyse échouée", exc_info=True)

    # ------------------------------------------------------------------
    # Ring buffer
    # ------------------------------------------------------------------
    def feed(self, samples: np.ndarray) -> None:
        """Ajoute des échantillons au ring buffer (thread capture ou tests)."""
        chunk = np.asarray(samples, dtype=np.float32)
        if chunk.ndim == 1:
            chunk = chunk[np.newaxis, :]
        if chunk.shape[0] != self._channels:
            raise ValueError(
                f"Attendu {self._channels} canaux, reçu {chunk.shape[0]}"
            )
        frames = chunk.shape[1]
        if frames == 0:
            return
        if frames > self._ring_size:
            chunk = chunk[:, -self._ring_size :]
            frames = self._ring_size

        with self._data_lock:
            end = self._write + frames
            if end <= self._ring_size:
                self._ring[:, self._write : end] = chunk
            else:
                first = self._ring_size - self._write
                self._ring[:, self._write :] = chunk[:, :first]
                self._ring[:, : end - self._ring_size] = chunk[:, first:]
            self._write = end % self._ring_size
            self._count = min(self._count + frames, self._ring_size)

    def latest(self, window_size: int) -> np.ndarray:
        """Retourne les ``window_size`` derniers frames, zéro-paddés à gauche."""
        size = max(int(window_size), 1)
        output = np.zeros((self._channels, size), dtype=np.float32)
        with self._data_lock:
            available = min(self._count, size)
            if available:
                indices = (np.arange(self._write - available, self._write)) % self._ring_size
                output[:, -available:] = self._ring[:, indices]
        return output

    # ------------------------------------------------------------------
    # Analyses
    # ------------------------------------------------------------------
    def _unavailable(self, index: int) -> dict[str, Any]:
        return {
            "index": index,
            "active": False,
            "error": self._error or "Analyse audio non démarrée",
        }

    def _check_index(self, index: int) -> dict[str, Any] | None:
        if not (self._running or self._offline):
            return self._unavailable(index)
        if index < 0 or index >= self._channels:
            return {
                "index": index,
                "active": False,
                "error": f"index {index} hors plage (0..{self._channels - 1})",
            }
        return None

    def analyze_rms(self, index: int = 0, window_size: int = 2048) -> dict[str, Any]:
        """Niveau RMS / peak sur les derniers ``window_size`` frames."""
        error = self._check_index(index)
        if error is not None:
            return error

        data = self.latest(window_size)[index].astype(np.float64)
        rms = float(np.sqrt(np.mean(data * data))) if data.size else 0.0
        peak = float(np.max(np.abs(data))) if data.size else 0.0
        return {
            "index": index,
            "rms_level": rms,
            "rms_db": _db(rms),
            "peak": peak,
            "peak_db": _db(peak),
            "window_size": int(window_size),
            "signal": rms > SILENCE_RMS,
            "active": True,
        }

    def analyze_pitch(self, index: int = 0) -> dict[str, Any]:
        """Fréquence fondamentale (autocorrélation) sur ~100 ms."""
        error = self._check_index(index)
        if error is not None:
            return error

        window = int(min(self._sample_rate * 0.1, self._ring_size))
        data = self.latest(window)[index]
        frequency, confidence = detect_pitch(data, self._sample_rate)
        midi = midi_note(frequency)
        return {
            "index": index,
            "pitch_detected": float(frequency) if frequency else 0.0,
            "frequency_hz": float(frequency) if frequency else None,
            "midi_note": midi,
            "note_name": note_name(midi),
            "confidence": confidence,
            "algorithm": "autocorrelation",
            "signal": frequency is not None,
            "active": True,
        }

    def analyze_frequency(self, index: int = 0, fft_size: int = 2048) -> dict[str, Any]:
        """Spectre FFT : fréquence dominante, centroïde et bandes d'énergie."""
        error = self._check_index(index)
        if error is not None:
            return error

        size = max(int(fft_size), 32)
        data = self.latest(size)[index].astype(np.float64)
        result: dict[str, Any] = {
            "index": index,
            "fft_size": size,
            "window": "hann",
            "sample_rate": self._sample_rate,
            "active": True,
        }
        if data.size == 0:
            signal = False
        else:
            signal = float(np.sqrt(np.mean(data * data))) >= SILENCE_RMS
        if not signal:
            result.update(
                {
                    "dominant_frequency_hz": None,
                    "spectral_centroid_hz": None,
                    "bands": {},
                    "peaks": [],
                    "signal": False,
                }
            )
            return result

        spectrum = np.abs(np.fft.rfft(data * np.hanning(data.size)))
        spectrum[0] = 0.0
        frequencies = np.fft.rfftfreq(data.size, d=1.0 / self._sample_rate)
        total = float(np.sum(spectrum))
        dominant = float(frequencies[int(np.argmax(spectrum))]) if total > 0 else None
        centroid = float(np.sum(frequencies * spectrum) / total) if total > 0 else None

        bands = {
            "low_hz": (0.0, 250.0),
            "low_mid_hz": (250.0, 500.0),
            "mid_hz": (500.0, 2000.0),
            "high_mid_hz": (2000.0, 6000.0),
            "high_hz": (6000.0, self._sample_rate / 2.0),
        }
        band_energy = {
            name: float(np.sum(spectrum[(frequencies >= low) & (frequencies < high)]) / total)
            if total > 0
            else 0.0
            for name, (low, high) in bands.items()
        }

        if spectrum.size > 2:
            maxima = np.where(
                (spectrum[1:-1] >= spectrum[:-2]) & (spectrum[1:-1] > spectrum[2:])
            )[0] + 1
            top = maxima[np.argsort(spectrum[maxima])[-5:]][::-1] if maxima.size else []
            peaks = [
                {
                    "frequency_hz": round(float(frequencies[i]), 2),
                    "magnitude_db": round(_db(spectrum[i]), 2),
                }
                for i in top
                if spectrum[i] > 0
            ]
        else:
            peaks = []

        result.update(
            {
                "dominant_frequency_hz": dominant,
                "spectral_centroid_hz": centroid,
                "bands": {name: round(value, 4) for name, value in band_energy.items()},
                "peaks": peaks,
                "signal": True,
            }
        )
        return result

    def analyze_audio_profile(self, index: int = 0) -> dict[str, Any]:
        """Profil complet : RMS, pitch, note MIDI, fréquence dominante."""
        error = self._check_index(index)
        if error is not None:
            return error

        rms_result = self.analyze_rms(index)
        pitch_result = self.analyze_pitch(index)
        frequency_result = self.analyze_frequency(index)
        return {
            "index": index,
            "rms": rms_result.get("rms_level"),
            "rms_db": rms_result.get("rms_db"),
            "peak_db": rms_result.get("peak_db"),
            "pitch": pitch_result.get("frequency_hz"),
            "midi_note": pitch_result.get("midi_note"),
            "note_name": pitch_result.get("note_name"),
            "confidence": pitch_result.get("confidence"),
            "dominant_frequency_hz": frequency_result.get("dominant_frequency_hz"),
            "spectral_centroid_hz": frequency_result.get("spectral_centroid_hz"),
            "fft_size": frequency_result.get("fft_size"),
            "window": frequency_result.get("window"),
            "signal": bool(rms_result.get("signal")),
            "active": True,
        }

    def get_midi_note(self, frequency_hz: float | None) -> int | None:
        """Compatibilité avec l'ancienne API pyo."""
        return midi_note(frequency_hz)


# ----------------------------------------------------------------------
# Analyseur global (utilisé par les tools MCP)
# ----------------------------------------------------------------------
_analyzer: AudioAnalyzer | None = None
_analyzer_lock = threading.Lock()


def get_analyzer() -> AudioAnalyzer | None:
    """Retourne (et démarre au besoin) l'analyseur global.

    L'analyseur s'appuie sur ``inputs[0]`` exposé dans ``__main__`` par
    ``main.py``. Retourne ``None`` si aucun input n'est disponible.
    """
    global _analyzer

    with _analyzer_lock:
        if _analyzer is None:
            main = sys.modules.get("__main__")
            inputs = main.__dict__.get("inputs", []) if main is not None else []
            if not inputs:
                return None
            _analyzer = AudioAnalyzer(inputs[0], open_capture=False)
        analyzer = _analyzer

    if not analyzer.running and analyzer.error is None:
        try:
            analyzer.start()
        except AudioAnalysisError:
            # L'erreur est conservée dans analyzer.error : les tools la
            # renvoient sans faire échouer le serveur audio.
            pass
    return analyzer


def close_analyzer() -> None:
    """Ferme l'analyseur global (appelé à l'arrêt du process)."""
    global _analyzer
    with _analyzer_lock:
        analyzer = _analyzer
        _analyzer = None
    if analyzer is not None:
        analyzer.close()


def set_analyzer(analyzer: AudioAnalyzer | None) -> None:
    """Remplace l'analyseur global (tests / intégration)."""
    global _analyzer
    with _analyzer_lock:
        _analyzer = analyzer
