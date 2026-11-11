#!/usr/bin/env python3
"""Retire les silences d'un WAV (streaming, adapte aux gros fichiers).

Usage:
    python scripts/remove_silence.py entree.wav sortie.wav
    python scripts/remove_silence.py entree.wav --stats-only
    python scripts/remove_silence.py entree.wav sortie.wav --threshold-db -40 --min-silence 0.3

Principe:
  1. Enveloppe RMS par fenetres de 20 ms (lecture en blocs).
  2. Les silences d'une duree >= --min-silence sont supprimes.
  3. Un padding de --padding-ms est conserve autour des passages joues.
  4. Fondu de --crossfade-ms aux jonctions (evite les clics).
  5. La taille de sortie est estimee avant d'ecrire (garde-fou disque).
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import wave
from typing import Self

import numpy as np

FRAME_MS = 20.0


class PcmReader:
    """Lecteur PCM 16 bits RIFF/RF64 (streaming, sans charger le fichier)."""

    def __init__(self, path: str) -> None:
        # Lecteur streaming : le fichier vit aussi longtemps que l'objet, la
        # fermeture est geree par close() / le protocole context manager.
        self.file = open(path, "rb")  # noqa: SIM115
        header = self.file.read(12)
        if len(header) < 12 or header[8:12] != b"WAVE":
            raise SystemExit("ce n'est pas un WAV (RIFF/RF64)")
        if header[:4] not in (b"RIFF", b"RF64"):
            raise SystemExit(f"format non supporte : {header[:4]!r}")

        ds64_data_size: int | None = None
        self.channels = self.rate = self.bits = None
        position = 12
        while True:
            self.file.seek(position)
            chunk = self.file.read(8)
            if len(chunk) < 8:
                raise SystemExit("chunk 'data' introuvable")
            chunk_id = chunk[:4]
            chunk_size = struct.unpack("<I", chunk[4:8])[0]
            if chunk_id == b"ds64":
                body = self.file.read(chunk_size)
                _riff_size, data_size, _sample_count, _table = struct.unpack("<QQQI", body[:28])
                ds64_data_size = data_size
            elif chunk_id == b"fmt ":
                body = self.file.read(chunk_size)
                _tag, channels, rate, _byte_rate, _align, bits = struct.unpack("<HHIIHH", body[:16])
                self.channels, self.rate, self.bits = channels, rate, bits
            elif chunk_id == b"data":
                if chunk_size == 0xFFFFFFFF and ds64_data_size is not None:
                    chunk_size = ds64_data_size
                self.data_offset = position + 8
                self.data_size = chunk_size
                break
            position += 8 + chunk_size + (chunk_size & 1)

        if self.channels is None or self.rate is None or self.bits is None:
            raise SystemExit("chunk 'fmt ' introuvable")
        if self.bits != 16:
            raise SystemExit(f"format non supporte : {self.bits} bits (16 attendu)")
        self.bytes_per_sample = self.bits // 8
        self.block_align = self.channels * self.bytes_per_sample
        self.total_frames = self.data_size // self.block_align

    def seek_frame(self, frame: int) -> None:
        self.file.seek(self.data_offset + frame * self.block_align)

    def read_frames(self, count: int) -> np.ndarray:
        raw = self.file.read(count * self.block_align)
        if not raw:
            return np.zeros(0, dtype=np.int16)
        return np.frombuffer(raw, dtype=np.int16)

    def close(self) -> None:
        self.file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def read_envelope(path: str, frame_ms: float = FRAME_MS) -> tuple[np.ndarray, dict]:
    """Retourne l'enveloppe RMS (float32, une valeur par fenetre) et les infos du WAV."""
    with PcmReader(path) as reader:
        channels = reader.channels
        rate = reader.rate
        total_frames = reader.total_frames
        sample_width = reader.bytes_per_sample

        frame_len = max(1, round(rate * frame_ms / 1000.0))
        block_frames = frame_len * 500  # ~10 s
        values: list[np.ndarray] = []
        carry = np.zeros(0, dtype=np.float32)

        remaining = total_frames
        while remaining > 0:
            chunk = reader.read_frames(min(block_frames, remaining))
            if chunk.size == 0:
                break
            remaining -= chunk.size // channels
            floats = chunk.astype(np.float32) / 32768.0
            if channels > 1:
                floats = floats.reshape(-1, channels).mean(axis=1)
            if carry.size:
                floats = np.concatenate((carry, floats))
            usable = (floats.size // frame_len) * frame_len
            if usable:
                frames = floats[:usable].reshape(-1, frame_len)
                values.append(np.sqrt(np.mean(frames * frames, axis=1)).astype(np.float32))
            carry = floats[usable:]

    if carry.size:
        values.append(np.array([np.sqrt(np.mean(carry * carry))], dtype=np.float32))

    envelope = np.concatenate(values) if values else np.zeros(0, dtype=np.float32)
    info = {
        "channels": channels,
        "sample_width": sample_width,
        "rate": rate,
        "n_frames": total_frames,
        "duration_s": total_frames / rate,
        "frame_s": frame_len / rate,
    }
    return envelope, info


def mask_to_segments(active: np.ndarray, frame_s: float, min_silence: float, padding: float,
                     total_s: float) -> list[tuple[float, float]]:
    """Convertit le masque actif en intervalles a conserver (en secondes)."""
    # 1. Silences = runs de False d'une duree >= min_silence
    segments: list[tuple[float, float]] = []
    start = None
    for i, value in enumerate(active):
        if value and start is None:
            start = i
        elif not value and start is not None:
            segments.append((start * frame_s, i * frame_s))
            start = None
    if start is not None:
        segments.append((start * frame_s, len(active) * frame_s))

    # 2. Padding autour de chaque passage, puis fusion des intervalles proches
    padded = [(max(0.0, s - padding), min(total_s, e + padding)) for s, e in segments]
    merged: list[tuple[float, float]] = []
    for s, e in padded:
        if merged and s <= merged[-1][1] + 0.05:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def write_segments(path: str, out_path: str, segments: list[tuple[float, float]],
                   info: dict, crossfade_s: float) -> int:
    """Ecrit les segments dans un nouveau WAV, avec fondus aux jonctions."""
    rate = info["rate"]
    channels = info["channels"]
    sample_width = info["sample_width"]
    xfade = max(1, round(crossfade_s * rate))

    written = 0
    with PcmReader(path) as reader, wave.open(out_path, "wb") as dst:
        dst.setnchannels(channels)
        dst.setsampwidth(sample_width)
        dst.setframerate(rate)

        for seg_index, (s, e) in enumerate(segments):
            i0 = round(s * rate)
            i1 = round(e * rate)
            length = i1 - i0
            if length <= 0:
                continue
            reader.seek_frame(i0)
            remaining = length
            first_block = True
            while remaining > 0:
                n = min(remaining, rate * 5)
                raw = reader.read_frames(n)
                if raw.size == 0:
                    break
                floats = raw.astype(np.float32) / 32768.0
                if channels > 1:
                    floats = floats.reshape(-1, channels)
                frames_read = floats.shape[0]

                # fondu d'entree sur le premier bloc du segment
                if first_block and xfade > 0:
                    k = min(xfade, frames_read)
                    ramp = np.linspace(0.0, 1.0, k, dtype=np.float32)
                    if channels > 1:
                        floats[:k] *= ramp[:, None]
                    else:
                        floats[:k] *= ramp
                    first_block = False

                # fondu de sortie sur le dernier bloc du segment
                if remaining <= frames_read and xfade > 0:
                    k = min(xfade, frames_read)
                    ramp = np.linspace(1.0, 0.0, k, dtype=np.float32)
                    if channels > 1:
                        floats[-k:] *= ramp[:, None]
                    else:
                        floats[-k:] *= ramp

                pcm = np.clip(floats * 32768.0, -32768, 32767).astype(np.int16)
                dst.writeframes(pcm.tobytes())
                written += frames_read
                remaining -= frames_read

            if (seg_index + 1) % 200 == 0:
                print(f"  ... {seg_index + 1}/{len(segments)} segments, "
                      f"{written / rate / 60:.1f} min ecrites", flush=True)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Retire les silences d'un WAV")
    parser.add_argument("source")
    parser.add_argument("destination", nargs="?")
    parser.add_argument("--threshold-db", type=float, default=-40.0,
                        help="seuil de silence (defaut -40 dB)")
    parser.add_argument("--min-silence", type=float, default=0.3,
                        help="duree minimale d'un silence a retirer (defaut 0.3 s)")
    parser.add_argument("--padding-ms", type=float, default=80.0,
                        help="silence conserve autour des passages joues (defaut 80 ms)")
    parser.add_argument("--crossfade-ms", type=float, default=10.0,
                        help="fondu aux jonctions (defaut 10 ms)")
    parser.add_argument("--stats-only", action="store_true")
    args = parser.parse_args()

    if not args.stats_only and not args.destination:
        parser.error("il faut un fichier de destination (ou --stats-only)")

    print(f"Lecture de l'enveloppe : {args.source}")
    envelope, info = read_envelope(args.source)
    if envelope.size == 0:
        print("fichier vide", file=sys.stderr)
        return 1

    db = 20.0 * np.log10(envelope + 1e-9)
    total_s = info["duration_s"]
    active = db >= args.threshold_db

    p10, p50, p90, p99 = np.percentile(db, [10, 50, 90, 99])
    print(f"  duree       : {total_s / 3600:.2f} h ({total_s:.1f} s)")
    print(f"  canaux      : {info['channels']} / {info['rate']} Hz / {info['sample_width'] * 8} bits")
    print(f"  niveaux dB  : p10={p10:.1f}  p50={p50:.1f}  p90={p90:.1f}  p99={p99:.1f}")
    print(f"  seuil       : {args.threshold_db} dB -> {active.mean() * 100:.1f} % du temps actif")

    segments = mask_to_segments(active, info["frame_s"], args.min_silence,
                                args.padding_ms / 1000.0, total_s)
    kept = sum(e - s for s, e in segments)
    print(f"  passages    : {len(segments)}")
    print(f"  conserve    : {kept / 60:.2f} min ({kept / total_s * 100:.2f} %)")
    size = int(kept * info["rate"] * info["channels"] * info["sample_width"])
    print(f"  taille est. : {size / 1024 ** 2:.1f} Mo")

    if size > 3_900_000_000:
        print("abandon : sortie > 3,9 Go (limite du WAV standard utilise en ecriture)",
              file=sys.stderr)
        return 1

    if args.stats_only:
        durations = sorted((e - s for s, e in segments), reverse=True)
        print("  plus longs passages (s) :", ", ".join(f"{d:.1f}" for d in durations[:10]))
        return 0

    free = os.statvfs(os.path.dirname(os.path.abspath(args.destination)))
    free_bytes = free.f_bavail * free.f_frsize
    if size > free_bytes * 0.9:
        print(f"abandon : pas assez de place ({free_bytes / 1024 ** 3:.1f} Go libres, "
              f"{size / 1024 ** 3:.1f} Go necessaires)", file=sys.stderr)
        return 1

    print(f"Ecriture de {args.destination} ...")
    written = write_segments(args.source, args.destination, segments, info,
                             args.crossfade_ms / 1000.0)
    print(f"Termine : {written / info['rate'] / 60:.2f} min ecrites "
          f"({os.path.getsize(args.destination) / 1024 ** 2:.1f} Mo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
