"""Point d'entrée Monkey Resonance — moteur audio Pedalboard.

Le serveur pyo a été remplacé par ``pedalboard.io.AudioStream``. Les noms
``AudioStream``, ``audio_devices`` et ``inputs`` restent exposés dans
``sys.modules["__main__"]`` : l'API REST et le serveur MCP s'appuient dessus.
"""

from __future__ import annotations

import argparse
import atexit
import logging
import os
import signal
import sys
from dataclasses import replace
from threading import Event, Thread
from typing import Any

from libs.audio_devices import AudioConfig, list_devices, load_config
from libs.audio_stream import AudioDeviceError, AudioStream
from libs.utils import APP_BASE_FOLDER, _check_and_create_app_folders

logger = logging.getLogger(__name__)

# Contrat historique lu par app/monkey_api/api.py et app/server/server.py via
# sys.modules["__main__"].__dict__. Ne pas renommer ni supprimer.
audio_devices: tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]] = ({}, {})
inputs: list[AudioStream] = []
stream: AudioStream | None = None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monkey Resonance audio engine")
    parser.add_argument(
        "--with_mcp",
        action="store_true",
        help="Démarre le MCP (activé par défaut ; conservé pour compatibilité).",
    )
    parser.add_argument(
        "--with_api",
        action="store_true",
        help="Démarre l'API REST à la place du MCP (même port).",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="Liste les périphériques Pedalboard puis quitte.",
    )
    parser.add_argument("--buffer-size", type=int, default=None)
    parser.add_argument("--sample-rate", type=int, default=None)
    return parser.parse_args()


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )


def _print_devices() -> None:
    device_inputs, device_outputs = list_devices()
    print("Entrées :")
    for index, device in device_inputs.items():
        marker = " (défaut)" if device["default"] else ""
        print(f"  {index}: {device['name']}{marker}")
    print("Sorties :")
    for index, device in device_outputs.items():
        marker = " (défaut)" if device["default"] else ""
        print(f"  {index}: {device['name']}{marker}")


def _start_engine(config: AudioConfig) -> AudioStream:
    engine = AudioStream(
        input_channel=0,
        input_device=config.input_device,
        output_device=config.output_device,
        record_device=config.record_device,
        sample_rate=config.sample_rate,
        buffer_size=config.buffer_size,
        num_input_channels=config.input_channels,
        num_output_channels=config.output_channels,
        global_volume=config.global_volume,
        allow_feedback=config.allow_feedback,
        start_muted=config.start_muted,
    )
    engine.start(unmute=not config.start_muted)

    logger.info(
        "Moteur audio prêt : in=%r out=%r sr=%g buffer=%s effects=%s",
        config.input_device,
        config.output_device,
        engine.sample_rate,
        engine.buffer_size,
        len(engine.effects_chain),
    )
    logger.info(
        "Enregistrement et analyse alimentés par le moteur (pas de capture secondaire)"
    )
    logger.info(
        "Latence logicielle : %.2f ms (capture %s frames + sortie %s frames)",
        engine.latency_ms,
        engine.capture_block_size,
        engine.buffer_size,
    )
    if config.start_muted:
        logger.info("Sortie démarrée en mute (AUDIO_START_MUTED=1)")
    return engine


def _run_mcp() -> None:
    from server.server import start_mcp

    start_mcp()


def _run_api() -> None:
    from monkey_api.api import start_api

    start_api()


def _wait_for_shutdown() -> None:
    shutdown = Event()

    def _handle_signal(signum: int, _frame: object) -> None:
        logger.info("Signal %s reçu, arrêt du moteur audio", signum)
        shutdown.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    shutdown.wait()


def main() -> int:
    global audio_devices, inputs, stream

    _configure_logging()
    args = _parse_args()

    if args.with_mcp and args.with_api:
        print(
            "Impossible de lancer le mcp et l'api en même temps "
            "(ils utilisent le même port)",
            file=sys.stderr,
        )
        return 2

    if args.list_devices:
        _print_devices()
        return 0

    _check_and_create_app_folders(APP_BASE_FOLDER)

    if not os.path.exists("/dev/snd"):
        logger.error("No audio shared with docker (/dev/snd absent)")
        return 1

    try:
        config = load_config()
    except (RuntimeError, ValueError) as exc:
        logger.error("Configuration audio invalide : %s", exc)
        return 1

    config = replace(
        config,
        buffer_size=args.buffer_size or config.buffer_size,
        sample_rate=args.sample_rate or config.sample_rate,
    )

    try:
        stream = _start_engine(config)
    except AudioDeviceError as exc:
        logger.error("%s", exc)
        _print_devices()
        return 1

    inputs = [stream]
    audio_devices = list_devices()
    atexit.register(stream.close)

    # Le MCP est activé par défaut (comportement de `main`) ; `--with_api`
    # le remplace, car les deux serveurs utilisent le même port.
    if not args.with_api:
        logger.info("Starting MCP server")
        Thread(target=_run_mcp, name="mcp-server", daemon=True).start()

    if args.with_api:
        logger.info("Starting REST API server")
        Thread(target=_run_api, name="api-server", daemon=True).start()
        print("REST API server started. Documentation disponible sur /docs")

    try:
        _wait_for_shutdown()
    except KeyboardInterrupt:
        logger.info("Interruption clavier, arrêt")
    finally:
        if stream is not None:
            stream.close()
        logger.info("Moteur audio arrêté")
    return 0


if __name__ == "__main__":
    sys.exit(main())
