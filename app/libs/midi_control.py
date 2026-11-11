"""Lecture MIDI brute ALSA pour les pédales et contrôleurs.

Le container n'expose pas ``/dev/snd/seq`` : ``mido``/``python-rtmidi`` ne
peuvent pas ouvrir l'ALSA sequencer. On lit donc directement les devices
``/dev/snd/midiC*D*`` (raw MIDI), qui fonctionnent même quand la carte audio
est ouverte en exclusif par Pedalboard.

Le module ne fait que :

- parser les octets MIDI (Program Change, CC, Note On/Off, running status) ;
- ouvrir le device, lire en non bloquant et transmettre les événements au
  ``PerformanceController`` ;
- se reconnecter si la pédale est débranchée.

Aucun appel audio n'est fait depuis ce thread.
"""

from __future__ import annotations

import glob
import logging
import os
import re
import select
import threading
from pathlib import Path
from typing import Any

from .performance import MidiEvent, PerformanceController

logger = logging.getLogger(__name__)

DEFAULT_RETRY_S = 2.0
SELECT_TIMEOUT_S = 0.2
READ_SIZE = 4096


def _read_sound_cards() -> list[dict[str, Any]]:
    """Retourne les cartes ALSA depuis ``/proc/asound/cards``."""
    path = Path("/proc/asound/cards")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    cards: list[dict[str, Any]] = []
    pattern = re.compile(r"^\s*(\d+)\s+\[([^\]]+)\]:\s*(.*)$")
    for line in lines:
        match = pattern.match(line)
        if not match:
            continue
        index, card_id, description = match.groups()
        cards.append(
            {
                "index": int(index),
                "id": card_id.strip(),
                "name": description.strip(),
            }
        )
    return cards


def list_midi_devices() -> list[dict[str, Any]]:
    """Liste les devices raw MIDI disponibles avec leur nom de carte."""
    cards = {card["index"]: card for card in _read_sound_cards()}
    devices: list[dict[str, Any]] = []
    for path in sorted(glob.glob("/dev/snd/midiC*D*")):
        match = re.search(r"midiC(\d+)D(\d+)$", path)
        if not match:
            continue
        card_index = int(match.group(1))
        device_index = int(match.group(2))
        card = cards.get(card_index, {})
        devices.append(
            {
                "path": path,
                "card_index": card_index,
                "device_index": device_index,
                "card_id": card.get("id"),
                "name": card.get("name"),
            }
        )
    return devices


def resolve_midi_device(spec: str | None = None) -> str | None:
    """Résout un chemin, un nom de carte ou ``None`` (premier device).

    Le container partage ``/dev/snd`` mais pas toujours ``/proc/asound``. Si le
    nom de carte ne peut pas être résolu faute de métadonnées ALSA, on retombe
    sur le premier device raw MIDI plutôt que de désactiver le MIDI.
    """
    if spec:
        if spec.startswith("/dev/"):
            return spec if os.path.exists(spec) else None
        cleaned = spec.strip()
        if cleaned.isdigit():
            matches = sorted(glob.glob(f"/dev/snd/midiC{int(cleaned)}D*"))
            return matches[0] if matches else None
        needle = cleaned.lower()
        cards = _read_sound_cards()
        for card in cards:
            haystack = f"{card['id']} {card['name']}".lower()
            if needle in haystack:
                matches = sorted(
                    glob.glob(f"/dev/snd/midiC{card['index']}D*")
                )
                if matches:
                    return matches[0]
        if not cards:
            matches = sorted(glob.glob("/dev/snd/midiC*D*"))
            if matches:
                logger.info(
                    "Device MIDI %r non résolu (pas de /proc/asound), "
                    "utilisation de %s",
                    spec,
                    matches[0],
                )
                return matches[0]
        # Un nom de device brut (hw:0,0,0) n'est pas ouvrable par os.open.
        return None
    matches = sorted(glob.glob("/dev/snd/midiC*D*"))
    return matches[0] if matches else None


class MidiStreamParser:
    """Parseur de flux MIDI brut, utilisable sans matériel dans les tests."""

    def __init__(self) -> None:
        self._status = 0
        self._data: list[int] = []
        self._sysex = False

    def feed(self, data: bytes) -> list[MidiEvent]:
        events: list[MidiEvent] = []
        for byte in data:
            # Real-time (clock, start, stop, active sensing...) : ignoré.
            if byte >= 0xF8:
                continue
            if self._sysex:
                if byte == 0xF7:
                    self._sysex = False
                continue
            if byte == 0xF0:
                self._sysex = True
                self._status = 0
                self._data = []
                continue
            if 0xF1 <= byte <= 0xF7:
                # System common / end of sysex : pas de running status.
                self._status = 0
                self._data = []
                continue
            if byte & 0x80:
                self._status = byte
                self._data = []
                continue
            if not 0x80 <= self._status <= 0xEF:
                continue
            self._data.append(byte)
            expected = 1 if (self._status & 0xF0) in (0xC0, 0xD0) else 2
            if len(self._data) >= expected:
                event = self._make_event()
                if event is not None:
                    events.append(event)
                self._data = []
        return events

    def _make_event(self) -> MidiEvent | None:
        status = self._status
        channel = status & 0x0F
        status_type = status & 0xF0
        data = self._data
        if status_type == 0x80:
            return MidiEvent(
                type="note_off",
                channel=channel,
                number=data[0],
                value=data[1],
            )
        if status_type == 0x90:
            note_on = data[1] > 0
            return MidiEvent(
                type="note_on" if note_on else "note_off",
                channel=channel,
                number=data[0],
                value=data[1],
            )
        if status_type == 0xB0:
            return MidiEvent(
                type="control_change",
                channel=channel,
                controller=data[0],
                value=data[1],
            )
        if status_type == 0xC0:
            return MidiEvent(
                type="program_change",
                channel=channel,
                number=data[0],
            )
        # Aftertouch, pitch bend, etc. : non utilisés par le mapping.
        return None


class MidiListener:
    """Thread de lecture raw MIDI avec reconnexion automatique."""

    def __init__(
        self,
        controller: PerformanceController,
        *,
        retry_s: float = DEFAULT_RETRY_S,
    ) -> None:
        self._controller = controller
        self._retry_s = max(float(retry_s), 0.1)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fd: int | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="midi-listener",
            daemon=True,
        )
        self._thread.start()
        logger.info("Listener MIDI démarré")

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            # Le thread sort de `select` en au plus SELECT_TIMEOUT_S et ferme
            # lui-même son descripteur : éviter un close() concurrent.
            thread.join(timeout=2.0)
        logger.info("Listener MIDI arrêté")

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop.is_set():
            spec = self._controller.device_spec
            path = resolve_midi_device(spec)
            if path is None:
                self._controller.set_midi_status(
                    connected=False,
                    device=spec,
                    error="Aucun device MIDI détecté",
                )
                self._stop.wait(self._retry_s)
                continue

            fd: int | None = None
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError as exc:
                self._controller.set_midi_status(
                    connected=False,
                    device=path,
                    error=str(exc),
                )
                logger.warning("Ouverture MIDI impossible (%s) : %s", path, exc)
                self._stop.wait(self._retry_s)
                continue

            with self._lock:
                self._fd = fd
            self._controller.set_midi_status(
                connected=True,
                device=path,
                error=None,
            )
            logger.info("MIDI connecté : %s", path)
            parser = MidiStreamParser()
            try:
                self._read_loop(fd, parser, spec)
            finally:
                with self._lock:
                    if self._fd == fd:
                        self._fd = None
                try:
                    os.close(fd)
                except OSError:
                    logger.debug("Fermeture MIDI échouée", exc_info=True)
                self._controller.set_midi_status(connected=False)
            if not self._stop.is_set():
                self._stop.wait(self._retry_s)

    def _read_loop(
        self,
        fd: int,
        parser: MidiStreamParser,
        spec: str | None,
    ) -> None:
        while not self._stop.is_set():
            # Si le profil actif change de device, on rouvre.
            if self._controller.device_spec != spec:
                return
            try:
                ready, _, _ = select.select([fd], [], [], SELECT_TIMEOUT_S)
            except (OSError, ValueError):
                return
            if not ready:
                continue
            try:
                data = os.read(fd, READ_SIZE)
            except BlockingIOError:
                continue
            except OSError as exc:
                self._controller.set_midi_status(error=str(exc))
                logger.warning("Lecture MIDI interrompue : %s", exc)
                return
            if not data:
                return
            for event in parser.feed(data):
                try:
                    self._controller.dispatch_event(event)
                except Exception:
                    logger.exception("Événement MIDI non traité : %s", event)


def start_midi_listener(
    controller: PerformanceController,
    *,
    retry_s: float = DEFAULT_RETRY_S,
) -> MidiListener:
    """Démarre un listener et le retourne."""
    listener = MidiListener(controller, retry_s=retry_s)
    listener.start()
    return listener
