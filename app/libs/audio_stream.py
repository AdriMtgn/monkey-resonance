"""Chaîne audio temps réel basée sur Pedalboard.

Ce module remplace l'implémentation pyo. Il garde la même API publique
(``add_effect``, ``remove_effect``, ``start``, ``stop``, ``save_effects``,
``load_effects``, ``start_recording``, ``stop_recording``) pour que l'API REST
et le serveur MCP continuent de fonctionner via ``sys.modules["__main__"]``.

Le processing (effets) tourne dans le callback C++ de
``pedalboard.io.AudioStream`` : pas de GIL dans le thread audio, et les
mutations de chaîne sont détectées par Pedalboard (polling ~5 ms + mutex).
Les mutations sont en plus sérialisées par un verrou côté control thread.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
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
# FIFO de la capture secondaire : assez large pour tolérer les pauses du
# thread Python d'écriture (~43 ms à 48 kHz), sans impacter le stream principal.
RECORD_BUFFER_SIZE = 2048


class AudioDeviceError(RuntimeError):
    """Erreur d'ouverture ou d'accès au périphérique audio."""


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
        global_volume: float = 1.0,
        allow_feedback: bool = False,
        start_muted: bool = False,
        open_device: bool = True,
    ) -> None:
        self.input_channel = input_channel
        self.input_device = input_device
        self.output_device = output_device
        # Par défaut, on enregistre depuis le même device que l'entrée
        # principale (dsnoop) : il accepte plusieurs captures simultanées.
        self.record_device = record_device if record_device is not None else input_device
        self._sample_rate = sample_rate
        self._buffer_size = buffer_size
        self.num_input_channels = num_input_channels
        self.num_output_channels = num_output_channels
        self.allow_feedback = allow_feedback

        self._lock = threading.RLock()
        self._slots: list[EffectSlot] = []
        self._volume = max(float(global_volume), 0.0)
        self._muted = bool(start_muted) or self._volume <= 0.0
        self._output_gain = Gain(gain_db=self._gain_db())
        self._board = Pedalboard([self._output_gain])
        self._stream: PedalboardAudioStream | None = None

        self.recording = False
        self._recording = False
        self._record_thread: threading.Thread | None = None
        self._record_writer: AudioFile | None = None
        self._record_stream: PedalboardAudioStream | None = None
        self._record_path: str | None = None

        if open_device:
            self._open_device()

    # ------------------------------------------------------------------
    # Device / stream lifecycle
    # ------------------------------------------------------------------
    def _open_device(self) -> None:
        last_error: Exception | None = None
        for attempt in range(1, MAX_OPEN_ATTEMPTS + 1):
            try:
                self._stream = PedalboardAudioStream(
                    input_device_name=self.input_device,
                    output_device_name=self.output_device,
                    plugins=self._board,
                    sample_rate=self._sample_rate,
                    buffer_size=self._buffer_size,
                    allow_feedback=self.allow_feedback,
                    num_input_channels=self.num_input_channels,
                    num_output_channels=self.num_output_channels,
                )
                logger.info(
                    "Périphérique audio ouvert : in=%r out=%r sr=%s buffer=%s",
                    self.input_device,
                    self.output_device,
                    self._stream.sample_rate,
                    self._stream.buffer_size,
                )
                return
            except (RuntimeError, ValueError, OSError) as exc:
                last_error = exc
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
            f"in={self.input_device!r} out={self.output_device!r}. "
            "Vérifie qu'aucun autre process (ancien container pyo, DAW, "
            f"PipeWire...) ne tient la carte. Entrées disponibles : {available}"
        ) from last_error

    def start(self, *, unmute: bool = True) -> None:
        """Démarre le stream (ou le relance).

        ``unmute=False`` garde la sortie muette dès l'ouverture : évite un
        court instant de sortie audible (click/larsen) au lancement.
        """
        with self._lock:
            if self._stream is None:
                self._open_device()
            if not self._stream.running:
                # AudioStream n'expose pas start()/stop() publics : le
                # context manager est la seule API de démarrage.
                self._stream.__enter__()
            if unmute:
                self._muted = False
            self._apply_gain()

    def stop(self) -> None:
        """Coupe la sortie sans fermer la carte (équivalent du mute pyo)."""
        with self._lock:
            self._muted = True
            self._apply_gain()

    def close(self) -> None:
        """Arrête l'enregistrement et ferme le périphérique audio."""
        with self._lock:
            if self.recording:
                self.stop_recording()
            if self._stream is not None and self._stream.running:
                self._stream.__exit__(None, None, None)
            self._stream = None

    @property
    def is_running(self) -> bool:
        return self._stream is not None and self._stream.running

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
        plugins = [plugin for slot in self._slots for plugin in slot.plugins]
        plugins.append(self._output_gain)
        self._board = Pedalboard(plugins)
        if self._stream is not None:
            self._stream.plugins = self._board

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
    def _open_record_stream(self) -> None:
        """Ouvre une capture secondaire partageable (dsnoop) pour l'enregistrement.

        Le stream principal utilise aussi le device dsnoop en entrée : ALSA
        autorise alors plusieurs clients de capture. Un device « direct
        hardware » serait exclusif et refuserait la seconde ouverture.
        """
        stream = PedalboardAudioStream(
            input_device_name=self.record_device,
            output_device_name=None,
            plugins=None,
            sample_rate=self.sample_rate,
            buffer_size=max(self._buffer_size, RECORD_BUFFER_SIZE),
            num_input_channels=self.num_input_channels,
            num_output_channels=0,
        )
        stream.ignore_dropped_input = True
        try:
            stream.__enter__()
        except (RuntimeError, ValueError, OSError) as exc:
            try:
                stream.close()
            except (RuntimeError, ValueError, OSError):
                logger.debug("Fermeture du stream d'enregistrement échouée", exc_info=True)
            raise AudioDeviceError(
                "Impossible d'ouvrir la capture secondaire pour l'enregistrement "
                f"sur {self.record_device!r}. L'entrée doit être un device "
                "partageable (dsnoop, « Direct sample snooping device ») et non "
                "un device matériel exclusif. Vérifie AUDIO_INPUT_DEVICE."
            ) from exc
        self._record_stream = stream

    def _close_record_stream(self) -> None:
        stream = self._record_stream
        self._record_stream = None
        if stream is not None and stream.running:
            try:
                stream.__exit__(None, None, None)
            except (RuntimeError, ValueError, OSError):
                logger.exception("Fermeture du stream d'enregistrement échouée")

    def start_recording(self, filename: str | None = None) -> str:
        """Démarre l'enregistrement de l'entrée brute (pas de la sortie).

        Pedalboard ne permet pas de tapper la sortie du callback C++ ; on
        enregistre donc le signal d'entrée via une seconde capture dsnoop, qui
        coexiste avec le stream principal. Un tap de sortie nécessiterait un
        moteur externe (JACK/ALSA loopback).
        """
        with self._lock:
            if self.recording:
                raise RuntimeError("Recording already in progress")
            if self._stream is None or not self._stream.running:
                raise RuntimeError("Audio stream is not running")

            if filename is None:
                import datetime

                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"record_{self.input_channel}_{timestamp}.wav"

            filename = Path(filename).name
            Path(records_folder).mkdir(parents=True, exist_ok=True)
            filepath = os.path.join(records_folder, filename)

            self._open_record_stream()
            try:
                self._record_writer = AudioFile(
                    filepath,
                    "w",
                    samplerate=float(self.sample_rate),
                    num_channels=self.num_input_channels,
                )
            except (RuntimeError, ValueError, OSError):
                self._close_record_stream()
                raise

            self._record_path = filepath
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
        while self._recording:
            stream = self._record_stream
            writer = self._record_writer
            if stream is None or writer is None:
                break
            try:
                chunk = stream.read(0)
                if chunk.size:
                    writer.write(chunk)
                else:
                    time.sleep(0.002)
            except (RuntimeError, ValueError, OSError):
                logger.exception("Erreur pendant l'enregistrement")
                self._recording = False

        # Vide ce qui reste dans le FIFO de capture avant la fermeture.
        stream = self._record_stream
        writer = self._record_writer
        if stream is not None and writer is not None:
            try:
                while True:
                    chunk = stream.read(0)
                    if not chunk.size:
                        break
                    writer.write(chunk)
            except (RuntimeError, ValueError, OSError):
                logger.exception("Erreur pendant le drainage de l'enregistrement")

    def stop_recording(self) -> str | None:
        """Arrête l'enregistrement et retourne le chemin du fichier."""
        with self._lock:
            if not self.recording:
                raise RuntimeError("No recording in progress")

            self._recording = False
            self.recording = False
            if self._record_thread is not None:
                self._record_thread.join(timeout=2.0)
                if self._record_thread.is_alive():
                    logger.warning("Le thread d'enregistrement ne s'est pas arrêté à temps")
                self._record_thread = None

            if self._record_writer is not None:
                self._record_writer.close()
                self._record_writer = None

            self._close_record_stream()

            filepath = self._record_path
            self._record_path = None
            logger.info("Enregistrement arrêté : %s", filepath)
            return filepath

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def read_available(self) -> np.ndarray:
        """Lit les frames d'entrée disponibles (diagnostic / monitoring)."""
        if self._stream is None:
            return np.empty((self.num_input_channels, 0), dtype=np.float32)
        return self._stream.read(0)

    @property
    def buffer_size(self) -> int:
        return int(self._stream.buffer_size) if self._stream else self._buffer_size

    @property
    def sample_rate(self) -> float:
        return float(self._stream.sample_rate) if self._stream else float(self._sample_rate)

    @property
    def latency_ms(self) -> float:
        return (self.buffer_size / self.sample_rate) * 1000.0

    @property
    def dropped_input_frame_count(self) -> int:
        return int(self._stream.dropped_input_frame_count) if self._stream else 0

    @property
    def buffered_input_sample_count(self) -> int:
        if self._stream is None:
            return 0
        return int(self._stream.buffered_input_sample_count or 0)

    def __str__(self) -> str:
        state = "running" if self.is_running else "stopped"
        return (
            f"AudioStream(input={self.input_device!r}, "
            f"output={self.output_device!r}, "
            f"sample_rate={self.sample_rate:g}, buffer_size={self.buffer_size}, "
            f"effects={len(self._slots)}, {state})"
        )

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
