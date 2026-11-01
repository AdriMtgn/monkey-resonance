"""Diagnostic audio Pedalboard : liste les devices et teste le stream live.

Exemples :
    python detect-sc.py                 # liste les périphériques résolus
    python detect-sc.py --test          # ouvre le stream 5 s, sortie muette
    python detect-sc.py --test --unmute # même chose mais avec la sortie active
"""

from __future__ import annotations

import argparse
import resource
import sys
import time
from dataclasses import replace

from libs.audio_devices import AudioConfig, list_devices, load_config
from libs.audio_stream import AudioDeviceError, AudioStream


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


def _print_config(config: AudioConfig) -> None:
    print(f"Entrée  : {config.input_device}")
    print(f"Sortie  : {config.output_device}")
    print(f"Enreg.  : {config.record_device}")
    print(
        f"Format  : {config.sample_rate} Hz, {config.buffer_size} frames, "
        f"{config.input_channels} in / {config.output_channels} out"
    )
    print(
        f"Latence : {config.buffer_latency_ms:.2f} ms/direction, "
        f"{config.round_trip_latency_ms:.2f} ms aller-retour théorique"
    )


def _run_test(engine: AudioStream, seconds: float, unmuted: bool) -> None:
    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    start = time.monotonic()
    dropped = 0
    buffer_size = engine.buffer_size
    sample_rate = engine.sample_rate
    latency_ms = engine.latency_ms

    try:
        while time.monotonic() - start < seconds:
            engine.read_available()
            dropped += engine.dropped_input_frame_count
            time.sleep(0.002)
    finally:
        usage_after = resource.getrusage(resource.RUSAGE_SELF)
        engine.close()

    wall = max(time.monotonic() - start, 1e-9)
    cpu = (
        (usage_after.ru_utime + usage_after.ru_stime)
        - (usage_before.ru_utime + usage_before.ru_stime)
    )
    print("\nRésultat du test :")
    print(f"  Durée                : {wall:.2f} s")
    print(f"  Buffer effectif      : {buffer_size} frames")
    print(f"  Sample rate effectif : {sample_rate:g} Hz")
    print(
        f"  Latence buffer       : {latency_ms:.2f} ms/direction, "
        f"{latency_ms * 2:.2f} ms aller-retour théorique"
    )
    print(f"  CPU process          : {cpu / wall * 100:.1f} % d'un cœur")
    print(f"  Frames d'entrée perdues : {dropped}")
    print(f"  Sortie               : {'active' if unmuted else 'muette'}")
    print(
        "\nNote : la latence aller-retour réelle dépend de l'USB et du matériel ; "
        "cette mesure est le buffer logiciel."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="Ouvre le stream live.")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--buffer-size", type=int, default=None)
    parser.add_argument("--sample-rate", type=int, default=None)
    parser.add_argument("--input-device", default=None)
    parser.add_argument("--output-device", default=None)
    parser.add_argument(
        "--unmute",
        action="store_true",
        help="Active la sortie pendant le test (attention au larsen).",
    )
    args = parser.parse_args()

    try:
        config = load_config()
    except (RuntimeError, ValueError) as exc:
        print(f"Erreur de configuration audio : {exc}", file=sys.stderr)
        return 1

    overrides = {
        "buffer_size": args.buffer_size or config.buffer_size,
        "sample_rate": args.sample_rate or config.sample_rate,
        "input_device": args.input_device or config.input_device,
        "output_device": args.output_device or config.output_device,
    }
    config = replace(config, **overrides)

    _print_devices()
    print()
    _print_config(config)

    if not args.test:
        return 0

    try:
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
            start_muted=not args.unmute,
        )
        engine.start(unmute=args.unmute)
    except AudioDeviceError as exc:
        print(f"\nErreur d'ouverture audio : {exc}", file=sys.stderr)
        return 1

    _run_test(engine, args.seconds, args.unmute)
    return 0


if __name__ == "__main__":
    sys.exit(main())
