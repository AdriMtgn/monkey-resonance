#!/usr/bin/env python3
"""Decoupe un extrait d'un WAV en boucle propre (fonds de 5 ms).

Usage:
    python scripts/cut_loop.py entree.wav sortie.wav --start 1.07 --end 10.32
    python scripts/cut_loop.py entree.wav sortie.wav --start 1.07 --bars 4 --bpm 103.4

Si --bars est fourni, la fin est calculee depuis le tempo :
    duree = bars * 4 * 60 / bpm
"""

from __future__ import annotations

import argparse

import numpy as np
import soundfile as sf


def main() -> int:
    parser = argparse.ArgumentParser(description="Decoupe une boucle propre dans un WAV")
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--start", type=float, required=True, help="debut en secondes")
    parser.add_argument("--end", type=float, default=None, help="fin en secondes")
    parser.add_argument("--bars", type=float, default=None, help="longueur en mesures (alternative a --end)")
    parser.add_argument("--bpm", type=float, default=None, help="tempo pour calculer --bars")
    parser.add_argument("--fade-ms", type=float, default=5.0)
    args = parser.parse_args()

    if args.end is None:
        if args.bars is None or args.bpm is None:
            parser.error("il faut --end ou (--bars et --bpm)")
        args.end = args.start + args.bars * 4 * 60.0 / args.bpm

    if args.end <= args.start:
        parser.error("--end doit etre superieur a --start")

    y, sr = sf.read(args.source, dtype="float32", always_2d=False)
    if y.ndim > 1:
        y = y.mean(axis=1)

    i0 = max(0, round(args.start * sr))
    i1 = min(len(y), round(args.end * sr))
    if i1 - i0 < int(0.05 * sr):
        parser.error("extrait trop court")

    out = y[i0:i1].copy()
    fade = int(max(1, round(args.fade_ms / 1000.0 * sr)))
    fade = min(fade, len(out) // 2)
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        out[:fade] *= ramp
        out[-fade:] *= ramp[::-1]

    sf.write(args.destination, out, sr)
    print(f"ecrit: {args.destination}")
    print(f"  {args.start:.3f}s -> {args.end:.3f}s = {len(out) / sr:.3f}s ({len(out)} frames, {sr} Hz)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
