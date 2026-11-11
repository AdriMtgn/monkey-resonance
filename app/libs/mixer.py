"""Moteur multi-pistes et mixeur global (latence first).

Le moteur historique ``AudioStream`` traitait un seul flux stéréo. Ici, un
``MixerEngine`` possède **une seule** capture et **une seule** lecture
Pedalboard, puis :

- découpe le bloc capté en pistes logiques (une piste = 1 ou 2 canaux) ;
- fait passer chaque piste dans sa propre chaîne d'effets ;
- applique le fader, la balance et les gains gauche/droite de la piste ;
- route chaque piste vers chaque **bus de sortie stéréo** avec un volume
  dédié (matrice ``input × output``) ;
- additionne les bus dans les canaux physiques de sortie.

Tout se fait dans le même bloc et le même thread que la capture. Il n'y a
donc **aucune file, aucun thread et aucun buffer supplémentaire** : la
latence reste celle d'un bloc de capture + un bloc de sortie, comme avant.
"""

from __future__ import annotations

import logging
import math
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from pedalboard.io import AudioStream as PedalboardAudioStream

from .audio_stream import (
    CAPTURE_BLOCK_MIN,
    CAPTURE_POLL_S,
    MIX_CEILING,
    AudioStream,
    open_device_pair,
)

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Description de la configuration
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class InputSpec:
    """Piste logique : un nom et les canaux de capture qu'elle traite."""

    name: str
    channels: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class OutputSpec:
    """Bus de sortie stéréo : un nom et la paire de canaux physiques."""

    name: str
    left_channel: int
    right_channel: int


@dataclass(slots=True)
class OutputBus:
    """Bus de sortie stéréo (fader + mute)."""

    index: int
    name: str
    left_channel: int
    right_channel: int
    volume: float = 1.0
    muted: bool = False

    def descriptor(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "left_channel": self.left_channel,
            "right_channel": self.right_channel,
            "volume": round(self.volume, 4),
            "muted": self.muted,
        }


@dataclass(slots=True)
class InputState:
    """État de mixage d'une piste (hors chaîne d'effets)."""

    name: str
    balance: float = 0.0
    left_gain: float = 1.0
    right_gain: float = 1.0
    # index du bus -> volume d'envoi
    routes: dict[int, float] = field(default_factory=dict)

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "balance": round(self.balance, 4),
            "left_gain": round(self.left_gain, 4),
            "right_gain": round(self.right_gain, 4),
            "routes": {str(index): round(level, 4) for index, level in self.routes.items()},
        }


# ----------------------------------------------------------------------
# Parsing de la configuration
# ----------------------------------------------------------------------
def _parse_channel_list(raw: str, num_channels: int, *, label: str) -> tuple[int, ...]:
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts:
        raise ValueError(f"{label} : aucun canal indiqué")
    try:
        channels = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise ValueError(f"{label} : canaux invalides ({raw!r})") from exc
    if len(channels) > 2:
        raise ValueError(f"{label} : 2 canaux maximum ({raw!r})")
    for channel in channels:
        if channel < 0 or channel >= num_channels:
            raise ValueError(
                f"{label} : canal {channel} hors plage (0..{num_channels - 1})"
            )
    return channels


def parse_input_layout(spec: str | None, num_channels: int) -> list[InputSpec]:
    """Parse ``AUDIO_INPUTS`` (``nom:canal[,canal][;...]``).

    Sans configuration, on crée une piste mono par canal capté : c'est le
    comportement par défaut demandé (``input_0`` sur le canal 0, etc.).
    """
    if not spec or not spec.strip():
        return [
            InputSpec(name=f"input_{channel}", channels=(channel,))
            for channel in range(num_channels)
        ]

    inputs: list[InputSpec] = []
    names: set[str] = set()
    for item in spec.split(";"):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(
                f"AUDIO_INPUTS : entrée invalide {item!r} "
                "(format attendu 'nom:canal[,canal]')"
            )
        name, raw_channels = item.split(":", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"AUDIO_INPUTS : nom manquant dans {item!r}")
        if name in names:
            raise ValueError(f"AUDIO_INPUTS : nom dupliqué {name!r}")
        names.add(name)
        channels = _parse_channel_list(
            raw_channels, num_channels, label=f"AUDIO_INPUTS/{name}"
        )
        inputs.append(InputSpec(name=name, channels=channels))

    if not inputs:
        raise ValueError("AUDIO_INPUTS ne contient aucune entrée")
    return inputs


def parse_output_layout(spec: str | None, num_channels: int) -> list[OutputSpec]:
    """Parse ``AUDIO_OUTPUTS`` (``nom:gauche[,droite][;...]``).

    Sans configuration, on crée un bus ``main`` sur les canaux 0/1 (ou 0/0 si
    la sortie est mono).
    """
    if not spec or not spec.strip():
        if num_channels >= 2:
            return [OutputSpec(name="main", left_channel=0, right_channel=1)]
        return [OutputSpec(name="main", left_channel=0, right_channel=0)]

    outputs: list[OutputSpec] = []
    names: set[str] = set()
    for item in spec.split(";"):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(
                f"AUDIO_OUTPUTS : sortie invalide {item!r} "
                "(format attendu 'nom:gauche[,droite]')"
            )
        name, raw_channels = item.split(":", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"AUDIO_OUTPUTS : nom manquant dans {item!r}")
        if name in names:
            raise ValueError(f"AUDIO_OUTPUTS : nom dupliqué {name!r}")
        names.add(name)
        channels = _parse_channel_list(
            raw_channels, num_channels, label=f"AUDIO_OUTPUTS/{name}"
        )
        left = channels[0]
        right = channels[1] if len(channels) > 1 else left
        outputs.append(OutputSpec(name=name, left_channel=left, right_channel=right))

    if not outputs:
        raise ValueError("AUDIO_OUTPUTS ne contient aucune sortie")
    return outputs


# ----------------------------------------------------------------------
# Moteur
# ----------------------------------------------------------------------
class MixerEngine:
    """Capture Pedalboard unique + pistes indépendantes + mixeur de bus."""

    def __init__(self, config: Any, *, open_device: bool = True) -> None:
        self.input_device = config.input_device
        self.output_device = config.output_device
        self.record_device = config.record_device
        self._sample_rate = int(config.sample_rate)
        self._buffer_size = int(config.buffer_size)
        self._capture_block = max(self._buffer_size, CAPTURE_BLOCK_MIN)
        self.num_input_channels = int(config.input_channels)
        self.num_output_channels = int(config.output_channels)

        self._lock = threading.RLock()
        self._capture: PedalboardAudioStream | None = None
        self._playback: PedalboardAudioStream | None = None
        self._audio_thread: threading.Thread | None = None
        self._running = False
        self._frames_read = 0
        self._clock_start = 0.0
        # Le mute de démarrage est appliqué piste par piste : chaque input
        # peut être unmute indépendamment, sans dépendre d'un mute master.
        self._start_muted = bool(getattr(config, "start_muted", False))
        self._muted = False
        self._master_volume = float(getattr(config, "master_volume", 1.0))
        self._listeners: tuple[Any, ...] = ()

        self._tracks: list[AudioStream] = []
        self._input_states: dict[AudioStream, InputState] = {}
        self._outputs: list[OutputBus] = []

        input_specs = parse_input_layout(
            getattr(config, "input_layout", None), self.num_input_channels
        )
        output_specs = parse_output_layout(
            getattr(config, "output_layout", None), self.num_output_channels
        )

        for spec in output_specs:
            self._outputs.append(
                OutputBus(
                    index=len(self._outputs),
                    name=spec.name,
                    left_channel=spec.left_channel,
                    right_channel=spec.right_channel,
                )
            )

        for spec in input_specs:
            self._append_input(spec)

        logger.info(
            "MixerEngine : %s piste(s) %s, %s bus %s, sortie %s canaux",
            len(self._tracks),
            [(state.name, track.input_channels) for track, state in self._input_states.items()],
            len(self._outputs),
            [(bus.name, bus.left_channel, bus.right_channel) for bus in self._outputs],
            self.num_output_channels,
        )

        if open_device:
            self._open_device()

    # ------------------------------------------------------------------
    # Construction des pistes / bus
    # ------------------------------------------------------------------
    def _append_input(self, spec: InputSpec) -> AudioStream:
        track = AudioStream(
            input_channel=spec.channels[0],
            input_channels=spec.channels,
            num_input_channels=len(spec.channels),
            num_output_channels=2,
            input_device=self.input_device,
            output_device=self.output_device,
            record_device=self.record_device,
            sample_rate=self._sample_rate,
            buffer_size=self._buffer_size,
            managed=True,
            name=spec.name,
            start_muted=self._start_muted,
            open_device=False,
        )
        track.attach_engine(self)
        state = InputState(
            name=spec.name,
            routes={index: (1.0 if index == 0 else 0.0) for index in range(len(self._outputs))},
        )
        self._tracks.append(track)
        self._input_states[track] = state
        return track

    # ------------------------------------------------------------------
    # Périphériques / cycle de vie
    # ------------------------------------------------------------------
    def _open_device(self) -> None:
        self._capture, self._playback = open_device_pair(
            input_device=self.input_device,
            output_device=self.output_device,
            sample_rate=self._sample_rate,
            capture_block=self._capture_block,
            buffer_size=self._buffer_size,
            num_input_channels=self.num_input_channels,
            num_output_channels=self.num_output_channels,
        )

    def start(self, *, unmute: bool = True) -> None:
        with self._lock:
            if self._capture is None or self._playback is None:
                self._open_device()
            if not self._running:
                self._capture.__enter__()
                try:
                    self._playback.__enter__()
                except (RuntimeError, ValueError, OSError):
                    try:
                        self._capture.__exit__(None, None, None)
                    except (RuntimeError, ValueError, OSError):
                        logger.exception("Fermeture de la capture après échec")
                    raise
                self._running = True
                self._frames_read = 0
                self._clock_start = time.monotonic()
                for track in self._tracks:
                    track._running = True
                self._audio_thread = threading.Thread(
                    target=self._audio_loop,
                    name="pedalboard-mixer",
                    daemon=True,
                )
                self._audio_thread.start()
            if unmute:
                self._muted = False
                for track in self._tracks:
                    track._muted = False
                    track._apply_gain()

    def stop(self) -> None:
        """Coupe la sortie globale (master mute) sans fermer la carte."""
        with self._lock:
            self._muted = True

    def mute(self) -> None:
        self.stop()

    def unmute(self) -> None:
        with self._lock:
            self._muted = False

    def close(self) -> None:
        with self._lock:
            self._running = False
            thread = self._audio_thread
            self._audio_thread = None
            capture = self._capture
            playback = self._playback
            self._capture = None
            self._playback = None
            tracks = tuple(self._tracks)

        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
            if thread.is_alive():
                logger.warning("Le thread audio ne s'est pas arrêté à temps")

        for stream in (capture, playback):
            if stream is None:
                continue
            try:
                if stream.running:
                    stream.__exit__(None, None, None)
                else:
                    stream.close()
            except (RuntimeError, ValueError, OSError):
                logger.exception("Fermeture d'un stream audio échouée")

        for track in tracks:
            track.close()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def sample_rate(self) -> float:
        return float(self._sample_rate)

    @property
    def buffer_size(self) -> int:
        return self._buffer_size

    @property
    def capture_block_size(self) -> int:
        return self._capture_block

    @property
    def latency_ms(self) -> float:
        """Latence logicielle : capture + sortie, sans buffer ajouté."""
        return (self._capture_block + self._buffer_size) / self.sample_rate * 1000.0

    @property
    def inputs(self) -> list[AudioStream]:
        return self._tracks

    @property
    def outputs(self) -> list[OutputBus]:
        return self._outputs

    @property
    def master_volume(self) -> float:
        return self._master_volume

    @master_volume.setter
    def master_volume(self, value: float) -> None:
        self._master_volume = max(float(value), 0.0)

    @property
    def global_volume(self) -> float:
        """Compatibilité analyseur : le master global du moteur."""
        return self._master_volume

    @property
    def effects_chain(self) -> list[dict[str, object]]:
        """Compatibilité : chaîne de la première piste (analyseur global)."""
        if not self._tracks:
            return []
        return self._tracks[0].effects_chain

    # ------------------------------------------------------------------
    # Thread audio / mixage
    # ------------------------------------------------------------------
    def _audio_loop(self) -> None:
        capture = self._capture
        playback = self._playback
        if capture is None or playback is None:
            return

        pending = np.empty((self.num_input_channels, 0), dtype=np.float32)
        block = self._capture_block
        logger.info(
            "Thread mixer démarré : blocs de %s frames (%.1f ms), %s pistes",
            block,
            block / self._sample_rate * 1000.0,
            len(self._tracks),
        )
        try:
            while self._running:
                chunk = capture.read(0)
                if chunk.size:
                    self._frames_read += chunk.shape[1]
                    pending = np.concatenate([pending, chunk], axis=1)

                while pending.shape[1] >= block:
                    if not self._running:
                        break
                    segment = np.ascontiguousarray(pending[:, :block])
                    pending = pending[:, block:]
                    self._process_block(segment, playback)

                if pending.shape[1] < block:
                    time.sleep(CAPTURE_POLL_S)
        except (RuntimeError, ValueError, OSError):
            logger.exception("Le thread mixer s'est arrêté sur une erreur")
        finally:
            logger.info("Thread mixer terminé")

    def _process_block(
        self, segment: np.ndarray, playback: PedalboardAudioStream
    ) -> None:
        with self._lock:
            tracks = tuple(self._tracks)
            # Instantané immuable : le thread audio ne doit pas itérer un dict
            # que le thread de contrôle peut modifier (add_output/remove_output).
            states = {
                track: (
                    self._input_states[track].left_gain,
                    self._input_states[track].right_gain,
                    self._input_states[track].balance,
                    tuple(self._input_states[track].routes.items()),
                )
                for track in tracks
            }
            outputs = tuple(self._outputs)
            master = self._master_volume
            muted = self._muted

        signals: list[np.ndarray] = []
        for track in tracks:
            signals.append(track.process_segment(track.extract(segment)))

        mixed = self._mix_signals(
            tracks, signals, states, outputs, frames=segment.shape[1]
        )
        if muted:
            mixed.fill(0.0)
        elif not math.isclose(master, 1.0):
            mixed *= master

        peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
        if peak > MIX_CEILING:
            mixed *= MIX_CEILING / peak

        listeners = self._listeners
        for listener in listeners:
            try:
                listener(segment, mixed)
            except Exception:  # un listener ne doit jamais tuer le thread audio
                logger.exception("Listener audio en erreur")

        playback.write(mixed, self._sample_rate)

    def _mix_signals(
        self,
        tracks: tuple[AudioStream, ...],
        signals: list[np.ndarray],
        states: dict[
            AudioStream, tuple[float, float, float, tuple[tuple[int, float], ...]]
        ],
        outputs: tuple[OutputBus, ...],
        *,
        frames: int,
    ) -> np.ndarray:
        mixed = np.zeros((self.num_output_channels, frames), dtype=np.float32)
        for track, signal in zip(tracks, signals, strict=True):
            left_gain, right_gain, balance, routes = states[track]
            left = signal[0] * left_gain
            right = signal[1] * right_gain
            # Balance linéaire : centre = unité, extrême = un côté à zéro.
            if balance > 0.0:
                left *= 1.0 - balance
            elif balance < 0.0:
                right *= 1.0 + balance

            for output_index, level in routes:
                if level <= 0.0 or output_index >= len(outputs):
                    continue
                bus = outputs[output_index]
                if bus.muted or bus.volume <= 0.0:
                    continue
                gain = level * bus.volume
                bus_left = left * gain
                bus_right = right * gain
                if bus.left_channel == bus.right_channel:
                    mixed[bus.left_channel] += 0.5 * (bus_left + bus_right)
                else:
                    mixed[bus.left_channel] += bus_left
                    mixed[bus.right_channel] += bus_right
        return mixed

    # ------------------------------------------------------------------
    # Listeners (analyse globale)
    # ------------------------------------------------------------------
    def add_listener(self, listener: Any) -> None:
        with self._lock:
            if listener not in self._listeners:
                self._listeners = (*self._listeners, listener)
                logger.info("Listener mixer ajouté : %r", listener)

    def remove_listener(self, listener: Any) -> None:
        with self._lock:
            self._listeners = tuple(
                existing for existing in self._listeners if existing != listener
            )
            logger.info("Listener mixer retiré : %r", listener)

    # ------------------------------------------------------------------
    # API de contrôle du mixer
    # ------------------------------------------------------------------
    def _track_at(self, index: int) -> AudioStream:
        try:
            return self._tracks[index]
        except (IndexError, TypeError) as exc:
            raise IndexError(f"Piste {index} introuvable") from exc

    def _output_at(self, index: int) -> OutputBus:
        try:
            return self._outputs[index]
        except (IndexError, TypeError) as exc:
            raise IndexError(f"Bus de sortie {index} introuvable") from exc

    def _validate_channels(self, channels: Any) -> tuple[int, ...]:
        try:
            values = tuple(int(channel) for channel in channels)
        except (TypeError, ValueError) as exc:
            raise ValueError("channels doit être une liste d'entiers") from exc
        if not values or len(values) > 2:
            raise ValueError("channels doit contenir 1 ou 2 canaux")
        for channel in values:
            if channel < 0 or channel >= self.num_input_channels:
                raise ValueError(
                    f"canal {channel} hors plage (0..{self.num_input_channels - 1})"
                )
        return values

    def add_input(self, name: str, channels: Any) -> dict[str, Any]:
        """Crée une piste indépendante sur les canaux de capture donnés."""
        clean_name = str(name).strip()
        if not clean_name:
            raise ValueError("Le nom de la piste ne peut pas être vide")
        values = self._validate_channels(channels)
        with self._lock:
            if any(state.name == clean_name for state in self._input_states.values()):
                raise ValueError(f"Une piste nommée {clean_name!r} existe déjà")
            track = self._append_input(InputSpec(clean_name, values))
            track._running = self._running
            index = len(self._tracks) - 1
            logger.info("Piste ajoutée : %s %s", clean_name, values)
            return {"index": index, "input": self._input_descriptor(index)}

    def remove_input(self, index: int) -> dict[str, Any]:
        """Retire une piste (les index suivants se décalent)."""
        with self._lock:
            track = self._track_at(index)
            descriptor = self._input_descriptor(index)
            self._tracks.pop(index)
            self._input_states.pop(track, None)
        track.close()
        logger.info("Piste retirée : %s", descriptor["name"])
        return {"result": "input_removed", "input": descriptor}

    def set_input_channels(self, index: int, channels: Any) -> dict[str, Any]:
        values = self._validate_channels(channels)
        with self._lock:
            track = self._track_at(index)
            track.set_input_channels(values)
            logger.info("Canaux de la piste %s : %s", track.name, values)
            return {"index": index, "channels": list(values)}

    def set_input_volume(self, index: int, volume: float) -> dict[str, Any]:
        with self._lock:
            track = self._track_at(index)
            track.global_volume = max(float(volume), 0.0)
            return {"index": index, "volume": round(track.global_volume, 4)}

    def set_input_mix(
        self,
        index: int,
        *,
        volume: float | None = None,
        balance: float | None = None,
        left_gain: float | None = None,
        right_gain: float | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            track = self._track_at(index)
            state = self._input_states[track]
            if volume is not None:
                track.global_volume = max(float(volume), 0.0)
            if balance is not None:
                state.balance = min(max(float(balance), -1.0), 1.0)
            if left_gain is not None:
                state.left_gain = max(float(left_gain), 0.0)
            if right_gain is not None:
                state.right_gain = max(float(right_gain), 0.0)
            return {"index": index, "input": self._input_descriptor(index)}

    def set_route(self, input_index: int, output_index: int, volume: float) -> dict[str, Any]:
        """Règle le volume d'envoi d'une piste vers un bus de sortie."""
        with self._lock:
            track = self._track_at(input_index)
            self._output_at(output_index)
            state = self._input_states[track]
            state.routes[output_index] = max(float(volume), 0.0)
            return {
                "input": input_index,
                "output": output_index,
                "volume": round(state.routes[output_index], 4),
            }

    def add_output(
        self, name: str, left_channel: int, right_channel: int | None = None
    ) -> dict[str, Any]:
        """Crée un bus de sortie stéréo mappé sur des canaux physiques."""
        clean_name = str(name).strip()
        if not clean_name:
            raise ValueError("Le nom du bus ne peut pas être vide")
        left = int(left_channel)
        right = int(right_channel) if right_channel is not None else left
        for channel in (left, right):
            if channel < 0 or channel >= self.num_output_channels:
                raise ValueError(
                    f"canal de sortie {channel} hors plage "
                    f"(0..{self.num_output_channels - 1})"
                )
        with self._lock:
            if any(bus.name == clean_name for bus in self._outputs):
                raise ValueError(f"Un bus nommé {clean_name!r} existe déjà")
            index = len(self._outputs)
            self._outputs.append(
                OutputBus(index=index, name=clean_name, left_channel=left, right_channel=right)
            )
            for state in self._input_states.values():
                state.routes.setdefault(index, 0.0)
            logger.info("Bus ajouté : %s (%s,%s)", clean_name, left, right)
            return {"index": index, "output": self._output_descriptor(index)}

    def remove_output(self, index: int) -> dict[str, Any]:
        """Retire un bus (les index suivants se décalent)."""
        with self._lock:
            descriptor = self._output_descriptor(index)
            self._outputs.pop(index)
            for position, bus in enumerate(self._outputs):
                bus.index = position
            for state in self._input_states.values():
                remapped: dict[int, float] = {}
                for old_index, level in state.routes.items():
                    if old_index == index:
                        continue
                    new_index = old_index - 1 if old_index > index else old_index
                    remapped[new_index] = level
                state.routes = remapped
            logger.info("Bus retiré : %s", descriptor["name"])
            return {"result": "output_removed", "output": descriptor}

    def set_output_channels(
        self, index: int, left_channel: int, right_channel: int | None = None
    ) -> dict[str, Any]:
        left = int(left_channel)
        right = int(right_channel) if right_channel is not None else left
        for channel in (left, right):
            if channel < 0 or channel >= self.num_output_channels:
                raise ValueError(
                    f"canal de sortie {channel} hors plage "
                    f"(0..{self.num_output_channels - 1})"
                )
        with self._lock:
            bus = self._output_at(index)
            bus.left_channel = left
            bus.right_channel = right
            return {"index": index, "output": self._output_descriptor(index)}

    def set_output_volume(self, index: int, volume: float) -> dict[str, Any]:
        with self._lock:
            bus = self._output_at(index)
            bus.volume = max(float(volume), 0.0)
            return {"index": index, "output": self._output_descriptor(index)}

    def mute_output(self, index: int) -> dict[str, Any]:
        with self._lock:
            bus = self._output_at(index)
            bus.muted = True
            return {"index": index, "output": self._output_descriptor(index)}

    def unmute_output(self, index: int) -> dict[str, Any]:
        with self._lock:
            bus = self._output_at(index)
            bus.muted = False
            return {"index": index, "output": self._output_descriptor(index)}

    def set_master_volume(self, volume: float) -> dict[str, Any]:
        self.master_volume = volume
        return {"master_volume": round(self._master_volume, 4)}

    # ------------------------------------------------------------------
    # État
    # ------------------------------------------------------------------
    def _input_descriptor(self, index: int) -> dict[str, Any]:
        track = self._track_at(index)
        state = self._input_states[track]
        return {
            "index": index,
            "name": state.name,
            "channels": list(track.input_channels),
            "volume": round(track.global_volume, 4),
            "muted": track._muted,
            "balance": round(state.balance, 4),
            "left_gain": round(state.left_gain, 4),
            "right_gain": round(state.right_gain, 4),
            "effects": track.effects_chain,
            "routes": {str(key): round(value, 4) for key, value in state.routes.items()},
            "playback": track.playback_status(),
        }

    def _output_descriptor(self, index: int) -> dict[str, Any]:
        return self._output_at(index).descriptor()

    def get_mixer_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "inputs": [
                    self._input_descriptor(index) for index in range(len(self._tracks))
                ],
                "outputs": [
                    self._output_descriptor(index) for index in range(len(self._outputs))
                ],
                "master_volume": round(self._master_volume, 4),
                "muted": self._muted,
                "latency_ms": round(self.latency_ms, 3),
                "capture_block_size": self._capture_block,
                "buffer_size": self._buffer_size,
            }


def mixer_from_main() -> tuple[MixerEngine | None, dict[str, Any] | None]:
    """Retourne le moteur depuis ``__main__`` (ou une erreur lisible)."""
    main = sys.modules.get("__main__")
    if main is None:
        return None, {"error": "__main__ not available"}
    engine = main.__dict__.get("stream")
    if engine is None:
        inputs = main.__dict__.get("inputs") or []
        if inputs:
            engine = getattr(inputs[0], "_engine", None)
    if engine is None:
        return None, {"error": "mixer engine not available"}
    return engine, None


__all__ = [
    "InputSpec",
    "InputState",
    "MixerEngine",
    "OutputBus",
    "OutputSpec",
    "mixer_from_main",
    "parse_input_layout",
    "parse_output_layout",
]
