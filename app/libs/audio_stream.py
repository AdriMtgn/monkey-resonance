"""Chaîne audio temps réel basée sur Pedalboard.

Ce module remplace l'implémentation pyo. Il garde la même API publique
(``add_effect``, ``remove_effect``, ``start``, ``stop``, ``save_effects``,
``load_effects``, ``start_recording``, ``stop_recording``) pour que l'API REST
et le serveur MCP continuent de fonctionner via ``sys.modules["__main__"]``.

Le traitement des effets et le mixage des boucles sont faits dans un thread
Python dédié (``_audio_loop``), à partir de deux streams Pedalboard :

- une **capture** seule, sur le device matériel direct ;
- une **lecture** seule, sur le même device matériel direct.

Pedalboard ne permet pas d'écrire dans le callback d'un stream duplex (le
``playBuffer`` est ignoré quand l'entrée et la sortie sont ouvertes ensemble),
d'où cette séparation. Les blocs sont traités avec ``reset=False`` : l'état des
filtres est conservé d'un bloc à l'autre (sinon un clic tous les ``buffer_size``
échantillons).

La capture est ouverte sur le device matériel direct (et non ``dsnoop``) : à
128 frames, elle délivre le débit réel (48 000 frames/s) avec une latence
minimale, alors que le dsnoop est calé sur la période du slave (1024 frames) et
ne remonte qu'une fraction du signal en dessous.

Comme la carte est alors ouverte en exclusif, l'enregistrement et l'analyse ne
peuvent pas ouvrir leur propre capture : ils sont **alimentés par le moteur**,
via les listeners (``add_listener``) et/ou une file bornée. Le thread audio ne
fait ainsi qu'un ``put_nowait`` (oublie le bloc si la file est pleine) : la
boucle et l'analyse n'ajoutent aucune latence au jeu live.
"""

from __future__ import annotations

import json
import logging
import math
import os
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from pedalboard import Gain, Pedalboard
from pedalboard.io import AudioFile
from pedalboard.io import AudioStream as PedalboardAudioStream

from .effect_lib import EffectSlot
from .utils import APP_BASE_FOLDER, APP_FOLDERS

logger = logging.getLogger(__name__)

records_folder = os.path.join(APP_BASE_FOLDER, APP_FOLDERS["RECORDS"])
effects_folder = os.path.join(APP_BASE_FOLDER, APP_FOLDERS["SAVED_EFFECTS"])

MAX_OPEN_ATTEMPTS = 3
OPEN_RETRY_DELAY_S = 0.4
# Nombre minimal de frames par bloc de capture. La capture se fait sur le
# device matériel direct (et non dsnoop) : à 128 frames, il délivre bien
# 48 000 frames/s. Avec le dsnoop, la période du slave est de 1024 frames et
# Pedalboard ne remonte qu'une fraction du signal en dessous (17 % à 128).
CAPTURE_BLOCK_MIN = 64
# Attente entre deux lectures non bloquantes de la capture.
CAPTURE_POLL_S = 0.0005
# Fondu appliqué en début et fin de boucle (évite le clic au raccord).
LOOP_FADE_S = 0.005
# Durée maximale d'une boucle chargée en mémoire (garde-fou disque/RAM).
MAX_LOOP_SECONDS = 600.0
# Marge de sécurité avant saturation lors du mix live + boucle.
MIX_CEILING = 0.99
# Profondeur de la file entre le thread audio et l'écriture WAV.
RECORD_QUEUE_SIZE = 256


class AudioDeviceError(RuntimeError):
    """Erreur d'ouverture ou d'accès au périphérique audio."""


def open_device_pair(
    *,
    input_device: str | int | None,
    output_device: str | int | None,
    sample_rate: int,
    capture_block: int,
    buffer_size: int,
    num_input_channels: int,
    num_output_channels: int,
) -> tuple[PedalboardAudioStream, PedalboardAudioStream]:
    """Ouvre la paire capture/lecture Pedalboard (avec quelques tentatives).

    La capture et la lecture sont deux streams séparés : Pedalboard n'écrit
    pas dans le callback d'un stream duplex. La fonction est partagée par le
    moteur mono-piste historique et par le moteur multi-pistes (``MixerEngine``)
    afin de garder exactement la même stratégie d'ouverture et de retry.
    """
    last_error: Exception | None = None
    for attempt in range(1, MAX_OPEN_ATTEMPTS + 1):
        capture: PedalboardAudioStream | None = None
        playback: PedalboardAudioStream | None = None
        try:
            capture = PedalboardAudioStream(
                input_device_name=input_device,
                output_device_name=None,
                plugins=None,
                sample_rate=sample_rate,
                buffer_size=capture_block,
                num_input_channels=num_input_channels,
                num_output_channels=0,
            )
            capture.ignore_dropped_input = True
            playback = PedalboardAudioStream(
                input_device_name=None,
                output_device_name=output_device,
                plugins=None,
                sample_rate=sample_rate,
                buffer_size=buffer_size,
                num_input_channels=0,
                num_output_channels=num_output_channels,
            )
            logger.info(
                "Périphériques ouverts : in=%r (bloc %s) out=%r (bloc %s) sr=%s",
                input_device,
                capture_block,
                output_device,
                buffer_size,
                sample_rate,
            )
            return capture, playback
        except (RuntimeError, ValueError, OSError) as exc:
            last_error = exc
            for stream in (capture, playback):
                if stream is not None:
                    try:
                        stream.close()
                    except (RuntimeError, ValueError, OSError):
                        logger.debug("Fermeture partielle échouée", exc_info=True)
            logger.warning(
                "Ouverture audio échouée (tentative %s/%s) : %s",
                attempt,
                MAX_OPEN_ATTEMPTS,
                exc,
            )
            if attempt < MAX_OPEN_ATTEMPTS:
                time.sleep(OPEN_RETRY_DELAY_S)

    available = ", ".join(PedalboardAudioStream.input_device_names)
    raise AudioDeviceError(
        "Impossible d'ouvrir le périphérique audio "
        f"in={input_device!r} out={output_device!r}. "
        "Vérifie qu'aucun autre process (ancien container pyo, DAW, "
        f"PipeWire...) ne tient la carte. Entrées disponibles : {available}"
    ) from last_error


class LoopPlayback:
    """Lecture d'un WAV (éventuellement bouclé) mixé avec le signal live.

    Seul le thread audio fait avancer ``position``. Les autres champs sont
    figés à la création : le buffer est immuable, donc pas de verrou.
    """

    def __init__(
        self,
        path: str,
        data: np.ndarray,
        *,
        loop: bool = True,
        volume: float = 1.0,
        sample_rate: float = 48000.0,
    ) -> None:
        self.path = path
        self.loop = bool(loop)
        self.volume = max(float(volume), 0.0)
        self.sample_rate = float(sample_rate)
        self.frames = int(data.shape[1])
        self.position = 0
        self.finished = False

        buffer = np.array(data, dtype=np.float32, copy=True)
        fade = int(LOOP_FADE_S * sample_rate)
        fade = max(0, min(fade, self.frames // 4))
        if fade:
            ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
            buffer[:, :fade] *= ramp
            buffer[:, -fade:] *= ramp[::-1]
        self._data = buffer * self.volume

    @property
    def duration_s(self) -> float:
        return self.frames / self.sample_rate if self.sample_rate else 0.0

    @property
    def position_s(self) -> float:
        return self.position / self.sample_rate if self.sample_rate else 0.0

    def next_block(self, num_frames: int) -> np.ndarray | None:
        """Retourne ``num_frames`` frames du buffer, ou ``None`` si terminé."""
        if self.finished or self.frames == 0:
            return None

        out = np.zeros((self._data.shape[0], num_frames), dtype=np.float32)
        filled = 0
        while filled < num_frames:
            remaining = self.frames - self.position
            take = min(remaining, num_frames - filled)
            out[:, filled : filled + take] = self._data[
                :, self.position : self.position + take
            ]
            self.position += take
            filled += take
            if self.position >= self.frames:
                if self.loop:
                    self.position = 0
                else:
                    self.finished = True
                    break
        return out

    def descriptor(self) -> dict[str, Any]:
        return {
            "file": self.path,
            "loop": self.loop,
            "volume": round(self.volume, 3),
            "duration_s": round(self.duration_s, 3),
            "position_s": round(self.position_s, 3),
            "finished": self.finished,
        }


class AudioStream:
    """Piste audio Pedalboard avec chaîne d'effets, mute et enregistrement."""

    def __init__(
        self,
        input_channel: int = 0,
        input_device: str | int | None = None,
        output_device: str | int | None = None,
        sample_rate: int = 48000,
        buffer_size: int = 128,
        num_input_channels: int = 2,
        num_output_channels: int = 2,
        *,
        record_device: str | int | None = None,
        input_channels: tuple[int, ...] | None = None,
        managed: bool = False,
        name: str | None = None,
        global_volume: float = 1.0,
        allow_feedback: bool = False,
        start_muted: bool = False,
        open_device: bool = True,
    ) -> None:
        # ``input_channels`` est la liste des canaux de capture traités par
        # cette piste. En mode ``managed`` (MixerEngine), une piste est un
        # sous-ensemble du flux capté (1 ou 2 canaux) et ne possède pas ses
        # propres périphériques : le moteur partagé s'en charge.
        self.input_channels = (
            tuple(int(channel) for channel in input_channels)
            if input_channels is not None
            else tuple(range(int(num_input_channels)))
        )
        if not self.input_channels:
            raise ValueError("input_channels ne peut pas être vide")
        self.input_channel = int(input_channel)
        if self.input_channel not in self.input_channels:
            self.input_channel = self.input_channels[0]
        self.name = name or f"input_{self.input_channel}"
        self.input_device = input_device
        self.output_device = output_device
        # Conservé pour compatibilité : l'enregistrement est désormais alimenté
        # par le moteur, plus par une capture secondaire.
        self.record_device = record_device if record_device is not None else input_device
        self._sample_rate = sample_rate
        self._buffer_size = buffer_size
        # Même taille que le buffer de sortie : la latence ajoutée par le
        # traitement est d'un bloc de capture + un bloc de lecture.
        self._capture_block = max(int(buffer_size), CAPTURE_BLOCK_MIN)
        self.num_input_channels = len(self.input_channels)
        self.num_output_channels = num_output_channels
        self.allow_feedback = allow_feedback
        self._managed = bool(managed)
        self._engine: Any | None = None

        self._lock = threading.RLock()
        # Verrou dédié à l'enregistrement : ouvrir/fermer une capture prend
        # plusieurs dizaines de ms et ne doit pas bloquer le thread audio.
        self._record_lock = threading.Lock()
        self._slots: list[EffectSlot] = []
        self._volume = max(float(global_volume), 0.0)
        self._muted = bool(start_muted) or self._volume <= 0.0
        self._output_gain = Gain(gain_db=self._gain_db())
        self._board = Pedalboard([self._output_gain])

        self._capture: PedalboardAudioStream | None = None
        self._playback: PedalboardAudioStream | None = None
        self._audio_thread: threading.Thread | None = None
        self._running = False
        self._last_input = np.empty((self.num_input_channels, 0), dtype=np.float32)
        self._frames_read = 0
        self._clock_start = 0.0

        self._loop: LoopPlayback | None = None
        self._loop_finished: LoopPlayback | None = None

        # Listeners alimentés depuis le thread audio : ``(dry, wet)``. Le tuple
        # est remplacé (et non muté) pour que le thread audio puisse l'itérer
        # sans verrou. Un listener doit être non bloquant (file bornée).
        self._listeners: tuple[Callable[[np.ndarray, np.ndarray], None], ...] = ()

        self.recording = False
        self._recording = False
        self._record_thread: threading.Thread | None = None
        self._record_writer: AudioFile | None = None
        # Le thread audio dépose le dry ici ; un thread d'écriture consomme.
        self._record_queue: queue.Queue[np.ndarray] | None = None
        self._record_path: str | None = None

        if open_device:
            self._open_device()

    # ------------------------------------------------------------------
    # Device / stream lifecycle
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
        """Démarre le stream (ou le relance).

        ``unmute=False`` garde la sortie muette dès l'ouverture : évite un
        court instant de sortie audible (click/larsen) au lancement.
        """
        with self._lock:
            if self._managed:
                # Piste gérée par un MixerEngine : les périphériques et le
                # thread audio appartiennent au moteur partagé.
                self._running = bool(
                    self._engine is not None and self._engine.is_running
                )
            else:
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
                    self._audio_thread = threading.Thread(
                        target=self._audio_loop,
                        name="pedalboard-audio",
                        daemon=True,
                    )
                    self._audio_thread.start()
            if unmute:
                self._muted = False
            self._apply_gain()

    def stop(self) -> None:
        """Coupe la sortie sans fermer la carte (équivalent du mute pyo)."""
        with self._lock:
            self._muted = True
            self._apply_gain()

    def close(self) -> None:
        """Arrête les streams et ferme les périphériques audio."""
        if self.recording:
            self.stop_recording()
        if self._managed:
            # Les périphériques appartiennent au MixerEngine : ne pas les
            # fermer ici, seulement arrêter la contribution de la piste.
            with self._lock:
                self._running = False
                self._loop = None
                self._loop_finished = None
            return
        with self._lock:
            self._running = False
            thread = self._audio_thread
            self._audio_thread = None
            capture = self._capture
            playback = self._playback
            self._capture = None
            self._playback = None

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

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Audio loop (processing + mix boucle)
    # ------------------------------------------------------------------
    def _audio_loop(self) -> None:
        capture = self._capture
        playback = self._playback
        if capture is None or playback is None:
            return

        pending = np.empty((self.num_input_channels, 0), dtype=np.float32)
        block = self._capture_block
        logger.info(
            "Thread audio démarré : blocs de %s frames (%.1f ms)",
            block,
            block / self._sample_rate * 1000.0,
        )
        try:
            while self._running:
                chunk = capture.read(0)
                if chunk.size:
                    self._last_input = chunk
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
            logger.exception("Le thread audio s'est arrêté sur une erreur")
        finally:
            logger.info("Thread audio terminé")

    def _process_block(
        self, segment: np.ndarray, playback: PedalboardAudioStream
    ) -> None:
        """Traite un bloc et l'écrit sur le stream de sortie (mode autonome)."""
        playback.write(self.process_segment(segment), self.sample_rate)

    def process_segment(self, segment: np.ndarray) -> np.ndarray:
        """Traite un bloc de cette piste et retourne le signal de sortie.

        C'est le point d'entrée utilisé par ``MixerEngine`` : la piste ne
        touche ni au périphérique ni au thread audio. Le signal retourné est
        au format du flux de sortie de la piste (stéréo par défaut), boucle
        incluse, mais **avant** le mixage global (balance, routage, bus).
        """
        with self._lock:
            board = self._board
            loop = self._loop
            muted = self._muted
            volume = self._volume

        wet = np.asarray(board.process(segment, self.sample_rate, reset=False))
        wet = np.asarray(wet, dtype=np.float32)
        if wet.ndim == 1:
            wet = wet[np.newaxis, :]
        wet = self._to_output_channels(wet)

        # Enregistrement et analyse sont alimentés ici, sans capture
        # secondaire (la carte est ouverte en exclusif). ``put_nowait`` ne
        # bloque jamais le thread audio : en cas de retard du consommateur, le
        # bloc est simplement ignoré plutôt que d'ajouter de la latence.
        record_queue = self._record_queue
        if record_queue is not None:
            try:
                record_queue.put_nowait(segment)
            except queue.Full:
                pass

        listeners = self._listeners
        for listener in listeners:
            try:
                listener(segment, wet)
            except Exception:  # un listener ne doit jamais tuer le thread audio
                logger.exception("Listener audio en erreur")

        mixed = wet
        if loop is not None:
            extra = loop.next_block(wet.shape[1])
            if extra is not None and not muted:
                if extra.shape != wet.shape:
                    extra = np.resize(extra, wet.shape)
                # Le fader de la piste (global_volume) s'applique aussi à la
                # boucle, qui est mixée après la chaîne d'effets.
                mixed = wet + extra * volume
                peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
                if peak > MIX_CEILING:
                    mixed = mixed * (MIX_CEILING / peak)
            if loop.finished:
                self._finish_loop(loop)

        return mixed

    def _to_output_channels(self, wet: np.ndarray) -> np.ndarray:
        """Adapte le signal traité au nombre de canaux de sortie de la piste.

        En mode ``managed``, une piste expose toujours une paire stéréo : le
        mixer a besoin de gauche/droite pour appliquer balance et gains. En
        mode autonome, on conserve le comportement historique (mono vers N
        canaux, stéréo conservé).
        """
        channels = self.num_output_channels
        if wet.shape[0] == channels:
            return wet
        if wet.shape[0] == 1:
            return np.repeat(wet, channels, axis=0)
        if wet.shape[0] > channels:
            return wet[:channels]
        # wet a 2 canaux et la sortie en demande davantage : duplication.
        repeats = (channels + wet.shape[0] - 1) // wet.shape[0]
        return np.vstack([wet] * repeats)[:channels]

    def extract(self, segment: np.ndarray) -> np.ndarray:
        """Extrait de ``segment`` les canaux de capture de cette piste."""
        channels = self.input_channels
        if not channels:
            return segment
        if segment.shape[0] <= max(channels):
            raise ValueError(
                f"La piste {self.name!r} attend les canaux {channels}, "
                f"mais le bloc n'en contient que {segment.shape[0]}"
            )
        return segment[list(channels), :]

    def attach_engine(self, engine: Any) -> None:
        """Rattache la piste à un ``MixerEngine`` (mode partagé)."""
        self._engine = engine
        self._managed = True
        self._sample_rate = engine.sample_rate
        self._buffer_size = engine.buffer_size
        self._capture_block = engine.capture_block_size

    def set_input_channels(self, channels: tuple[int, ...]) -> None:
        """Change les canaux de capture traités par la piste."""
        if not channels:
            raise ValueError("channels ne peut pas être vide")
        if self.recording:
            raise RuntimeError(
                "Impossible de changer les canaux pendant un enregistrement"
            )
        with self._lock:
            self.input_channels = tuple(int(channel) for channel in channels)
            self.input_channel = self.input_channels[0]
            self.num_input_channels = len(self.input_channels)
            self._rebuild_board()

    def _finish_loop(self, loop: LoopPlayback) -> None:
        with self._lock:
            if self._loop is loop:
                self._loop = None
                self._loop_finished = loop
        logger.info("Lecture terminée : %s", loop.path)

    # ------------------------------------------------------------------
    # Listeners (analyse, monitoring)
    # ------------------------------------------------------------------
    def add_listener(
        self, listener: Callable[[np.ndarray, np.ndarray], None]
    ) -> None:
        """Enregistre un callback ``(dry, wet)`` appelé à chaque bloc.

        Le callback tourne dans le thread audio : il doit être **non
        bloquant** (déposer les échantillons dans une file bornée et rendre la
        main immédiatement). ``dry`` est l'entrée brute, ``wet`` la sortie
        post-effets (avant mix de la boucle).
        """
        with self._lock:
            if listener not in self._listeners:
                self._listeners = (*self._listeners, listener)
                logger.info("Listener audio ajouté : %r", listener)

    def remove_listener(
        self, listener: Callable[[np.ndarray, np.ndarray], None]
    ) -> None:
        with self._lock:
            # Comparaison par égalité (pas identité) : un bound method est
            # recréé à chaque accès à ``self._on_audio``.
            self._listeners = tuple(
                existing for existing in self._listeners if existing != listener
            )
            logger.info("Listener audio retiré : %r", listener)

    # ------------------------------------------------------------------
    # Lecture des enregistrements (looper)
    # ------------------------------------------------------------------
    @property
    def playback(self) -> LoopPlayback | None:
        return self._loop

    def play_recording(
        self,
        filename: str,
        *,
        loop: bool = True,
        volume: float = 1.0,
    ) -> dict[str, Any]:
        """Charge un WAV de ``records/`` et le mixe avec le signal live."""
        path = (
            filename
            if os.path.isabs(filename)
            else os.path.join(records_folder, filename)
        )
        if not os.path.exists(path):
            raise FileNotFoundError(f"Enregistrement introuvable : {path}")
        if not self.is_running:
            raise RuntimeError("Audio stream is not running")

        playback = self._load_loop(path, loop=loop, volume=volume)
        with self._lock:
            self._loop = playback
            self._loop_finished = None
        logger.info(
            "Lecture démarrée : %s (%.2f s, boucle=%s, volume=%.2f)",
            path,
            playback.duration_s,
            playback.loop,
            playback.volume,
        )
        return playback.descriptor()

    def _load_loop(
        self, path: str, *, loop: bool, volume: float
    ) -> LoopPlayback:
        with AudioFile(path) as raw:
            duration = raw.frames / raw.samplerate if raw.samplerate else 0.0
            if duration > MAX_LOOP_SECONDS:
                raise ValueError(
                    f"Enregistrement trop long ({duration:.0f} s, "
                    f"max {MAX_LOOP_SECONDS:.0f} s)"
                )
            source = raw.resampled_to(self.sample_rate)
            data = source.read(source.frames)

        if data.shape[0] == 1:
            data = np.vstack([data[0], data[0]])
        data = np.ascontiguousarray(data[: self.num_output_channels], dtype=np.float32)
        return LoopPlayback(
            path,
            data,
            loop=loop,
            volume=volume,
            sample_rate=self.sample_rate,
        )

    def stop_playback(self) -> dict[str, Any] | None:
        """Arrête la boucle en cours et retourne son descripteur."""
        with self._lock:
            loop = self._loop
            self._loop = None
        if loop is None:
            return None
        loop.finished = True
        logger.info("Lecture arrêtée : %s", loop.path)
        return loop.descriptor()

    def playback_status(self) -> dict[str, Any] | None:
        loop = self._loop
        if loop is not None:
            return loop.descriptor()
        if self._loop_finished is not None:
            return self._loop_finished.descriptor()
        return None

    # ------------------------------------------------------------------
    # Volume / mute
    # ------------------------------------------------------------------
    def _gain_db(self) -> float:
        if self._muted or self._volume <= 0.0:
            return -100.0
        return 20.0 * math.log10(self._volume)

    def _apply_gain(self) -> None:
        self._output_gain.gain_db = self._gain_db()

    @property
    def global_volume(self) -> float:
        return self._volume

    @global_volume.setter
    def global_volume(self, value: float) -> None:
        self._volume = max(float(value), 0.0)
        self._apply_gain()

    def mute(self) -> None:
        self.stop()

    def unmute(self) -> None:
        self.start()

    # ------------------------------------------------------------------
    # Effects chain
    # ------------------------------------------------------------------
    @property
    def effects_chain(self) -> list[dict[str, object]]:
        return [slot.descriptor() for slot in self._slots]

    def _rebuild_board(self) -> None:
        plugins = [
            plugin
            for slot in self._slots
            if slot.enabled
            for plugin in slot.plugins
        ]
        plugins.append(self._output_gain)
        self._board = Pedalboard(plugins)

    @staticmethod
    def _effect_path(effect: str | type) -> str:
        if isinstance(effect, str):
            return effect
        if isinstance(effect, type):
            return f"{effect.__module__}.{effect.__name__}"
        raise TypeError("effect doit être un chemin 'module.Classe' ou une classe")

    def add_effect(
        self,
        position: int | None,
        effect: str | type,
        **kwargs: Any,
    ) -> None:
        """Ajoute un effet à la position donnée (None = fin de chaîne)."""
        with self._lock:
            if position is None:
                position = len(self._slots)
            if position < 0 or position > len(self._slots):
                raise IndexError("Invalid position for adding an effect.")

            slot = EffectSlot.create(self._effect_path(effect), kwargs)
            self._slots.insert(position, slot)
            self._rebuild_board()
            logger.info(
                "Effet ajouté à la position %s : %s %s",
                position,
                slot.path,
                slot.params,
            )

    def remove_effect(self, index: int) -> None:
        """Retire l'effet à l'index donné."""
        with self._lock:
            if index < 0 or index >= len(self._slots):
                raise IndexError("Invalid index for removing an effect.")
            slot = self._slots.pop(index)
            self._rebuild_board()
            logger.info("Effet retiré à l'index %s : %s", index, slot.path)

    def update_effect(self, position: int | None, **kwargs: Any) -> None:
        """Met à jour les paramètres de l'effet à la position donnée."""
        if position is None:
            raise IndexError("Index can't be None to select an effect.")
        with self._lock:
            if position < 0 or position >= len(self._slots):
                raise IndexError("Invalid position, no effect at this index.")
            slot = self._slots[position]
            slot.params.update(kwargs)
            slot.rebuild()
            self._rebuild_board()
            logger.info(
                "Effet mis à jour à la position %s : %s %s",
                position,
                slot.path,
                slot.params,
            )

    def set_effect_enabled(self, position: int, enabled: bool) -> dict[str, Any]:
        """Active ou bypass l'effet à ``position`` sans le retirer de la chaîne."""
        with self._lock:
            if position < 0 or position >= len(self._slots):
                raise IndexError("Invalid position, no effect at this index.")
            slot = self._slots[position]
            slot.enabled = bool(enabled)
            self._rebuild_board()
            logger.info(
                "Effet %s à la position %s : %s",
                "activé" if slot.enabled else "bypassé",
                position,
                slot.path,
            )
            return {"position": position, **slot.descriptor()}

    def toggle_effect(self, position: int) -> dict[str, Any]:
        """Inverse l'état actif/bypass de l'effet à ``position``."""
        with self._lock:
            if position < 0 or position >= len(self._slots):
                raise IndexError("Invalid position, no effect at this index.")
            return self.set_effect_enabled(
                position,
                not self._slots[position].enabled,
            )

    def effect_positions(self, effect: str | int | None = None) -> list[int]:
        """Retourne les positions correspondant à un chemin ou un index.

        ``None`` retourne toutes les positions. Un chemin peut correspondre à
        plusieurs effets identiques dans la chaîne ; l'appelant décide alors
        s'il agit sur le premier ou sur tous.
        """
        with self._lock:
            if effect is None:
                return list(range(len(self._slots)))
            if isinstance(effect, int):
                if effect < 0 or effect >= len(self._slots):
                    raise IndexError("Invalid position, no effect at this index.")
                return [effect]
            return [
                index
                for index, slot in enumerate(self._slots)
                if slot.path == effect
            ]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save_effects(self, effect_name: str) -> str:
        """Sauvegarde la chaîne dans ``saved_effects/<effect_name>.json``."""
        with self._lock:
            Path(effects_folder).mkdir(parents=True, exist_ok=True)
            filepath = os.path.join(effects_folder, f"{effect_name}.json")
            saved_data = {
                "engine": "pedalboard",
                "effect_chain": self.effects_chain,
                "global_volume": self._volume,
            }
            with open(filepath, "w", encoding="utf-8") as file:
                json.dump(saved_data, file, indent=4)
            logger.info("Chaîne d'effets sauvegardée dans %s", filepath)
            return filepath

    def load_effects(self, effect_name: str) -> None:
        """Charge une chaîne depuis ``saved_effects/<effect_name>.json``."""
        filepath = os.path.join(effects_folder, f"{effect_name}.json")
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Effect file '{filepath}' not found.")

        with open(filepath, encoding="utf-8") as file:
            saved_data = json.load(file)

        if isinstance(saved_data, list):
            chain = saved_data
            volume = 1.0
        else:
            chain = saved_data.get("effect_chain", [])
            volume = float(saved_data.get("global_volume", 1.0))

        if not isinstance(chain, list):
            raise TypeError(f"Format de chaîne invalide dans {filepath}")

        # Construit la nouvelle chaîne avant de remplacer l'ancienne : en cas
        # d'effet inconnu, la chaîne en cours reste intacte.
        new_slots = [
            EffectSlot.create(
                str(effect_infos["effect"]),
                effect_infos.get("params", {}),
                enabled=bool(effect_infos.get("enabled", True)),
            )
            for effect_infos in chain
        ]

        with self._lock:
            self._slots = new_slots
            self._volume = max(volume, 0.0)
            self._rebuild_board()
            self._apply_gain()
        logger.info("Chaîne d'effets chargée depuis %s", filepath)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def start_recording(self, filename: str | None = None) -> str:
        """Démarre l'enregistrement de l'entrée brute (pas de la sortie).

        La capture principale est ouverte en exclusif sur le device matériel
        direct : impossible d'ouvrir une seconde capture. Le thread audio
        dépose donc chaque bloc dry dans une file bornée, consommée par un
        thread d'écriture dédié. Le ``put_nowait`` ne bloque jamais le jeu.
        """
        with self._record_lock:
            if self.recording:
                raise RuntimeError("Recording already in progress")
            if not self.is_running:
                raise RuntimeError("Audio stream is not running")

            if filename is None:
                import datetime

                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"record_{self.input_channel}_{timestamp}.wav"

            filename = Path(filename).name
            Path(records_folder).mkdir(parents=True, exist_ok=True)
            filepath = os.path.join(records_folder, filename)

            writer = AudioFile(
                filepath,
                "w",
                samplerate=float(self.sample_rate),
                num_channels=self.num_input_channels,
            )

            self._record_writer = writer
            self._record_path = filepath
            self._record_queue = queue.Queue(maxsize=RECORD_QUEUE_SIZE)
            self._recording = True
            self.recording = True
            self._record_thread = threading.Thread(
                target=self._record_loop,
                name="pedalboard-recorder",
                daemon=True,
            )
            self._record_thread.start()
            logger.info("Enregistrement démarré : %s (entrée brute)", filepath)
            return filepath

    def _record_loop(self) -> None:
        record_queue = self._record_queue
        if record_queue is None:
            return
        while True:
            try:
                chunk = record_queue.get(timeout=0.1)
            except queue.Empty:
                if not self._recording:
                    break
                continue

            writer = self._record_writer
            if writer is None:
                break
            try:
                writer.write(chunk)
            except (RuntimeError, ValueError, OSError):
                logger.exception("Erreur pendant l'enregistrement")
                self._recording = False
                break

    def stop_recording(self) -> str | None:
        """Arrête l'enregistrement et retourne le chemin du fichier."""
        with self._record_lock:
            if not self.recording:
                raise RuntimeError("No recording in progress")

            self._recording = False
            self.recording = False
            # Détache la file : le thread audio cesse immédiatement d'y
            # déposer, puis le thread d'écriture draine ce qui reste.
            record_queue = self._record_queue
            self._record_queue = None
            if self._record_thread is not None:
                self._record_thread.join(timeout=2.0)
                if self._record_thread.is_alive():
                    logger.warning("Le thread d'enregistrement ne s'est pas arrêté à temps")
                self._record_thread = None
            if record_queue is not None:
                record_queue.queue.clear()

            if self._record_writer is not None:
                self._record_writer.close()
                self._record_writer = None

            filepath = self._record_path
            self._record_path = None
            logger.info("Enregistrement arrêté : %s", filepath)
            return filepath

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def read_available(self) -> np.ndarray:
        """Dernier bloc d'entrée capté (diagnostic / monitoring)."""
        return self._last_input

    @property
    def buffer_size(self) -> int:
        return self._buffer_size

    @property
    def capture_block_size(self) -> int:
        return self._capture_block

    @property
    def sample_rate(self) -> float:
        return float(self._sample_rate)

    @property
    def latency_ms(self) -> float:
        """Latence logicielle estimée (bloc de capture + FIFO de sortie)."""
        return (self._capture_block + self._buffer_size) / self.sample_rate * 1000.0

    @property
    def dropped_input_frame_count(self) -> int:
        """Frames manquantes estimées d'après l'horloge murale."""
        if not self._running or self._clock_start <= 0:
            return 0
        expected = (time.monotonic() - self._clock_start) * self.sample_rate
        return max(0, int(expected - self._frames_read))

    @property
    def buffered_input_sample_count(self) -> int:
        capture = self._capture
        if capture is None:
            return 0
        return int(capture.buffered_input_sample_count or 0)

    def __str__(self) -> str:
        state = "running" if self.is_running else "stopped"
        return (
            f"AudioStream(name={self.name!r}, channels={self.input_channels}, "
            f"input={self.input_device!r}, output={self.output_device!r}, "
            f"sample_rate={self.sample_rate:g}, buffer_size={self.buffer_size}, "
            f"effects={len(self._slots)}, {state})"
        )

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
