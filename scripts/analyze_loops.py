#!/usr/bin/env python3
"""Analyse un enregistrement pour detecter les boucles et les sections.

Usage:
    python scripts/analyze_loops.py /monkey-resonance/records/xxx.wav
    python scripts/analyze_loops.py xxx.wav --json

Methode:
  1. Beat tracking (librosa) -> tempo, positions des temps.
  2. Chroma synchronisee aux temps -> auto-similarite (cosinus).
  3. Recherche de la periode de repetition (en temps/mesures).
  4. Detection des changements de section (nouveaute sur le chroma).
  5. Pour chaque section : duree, accords par mesure, meilleure boucle.

Dependances (venv d'analyse isole) :
    uv pip install scipy librosa soundfile
"""

from __future__ import annotations

import argparse
import json
import sys

import librosa
import numpy as np
import soundfile as sf
from scipy.signal import find_peaks

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJOR = [0, 4, 7]
MINOR = [0, 3, 7]


def load_audio(path: str) -> tuple[np.ndarray, int]:
    y, sr = sf.read(path, dtype="float32", always_2d=False)
    if y.ndim > 1:
        y = y.mean(axis=1)
    return y, sr


def chord_from_chroma(vec: np.ndarray) -> tuple[str, float]:
    """Reconnaissance d'accord simple (majeur/mineur) par correlation."""
    norm = float(np.linalg.norm(vec))
    if norm < 1e-9:
        return "-", 0.0
    v = vec / norm
    best_name, best_score = "-", -1.0
    for root in range(12):
        for intervals, quality in ((MAJOR, ""), (MINOR, "m")):
            template = np.zeros(12)
            for i in intervals:
                template[(root + i) % 12] = 1.0
            template /= np.linalg.norm(template)
            score = float(np.dot(v, template))
            if score > best_score:
                best_score = score
                best_name = NOTE_NAMES[root] + quality
    return best_name, best_score


def diag_score(sim: np.ndarray, lag: int) -> tuple[float, float]:
    """Similarite moyenne sur la diagonale decalee de `lag` temps."""
    if lag <= 0 or lag >= sim.shape[0]:
        return 0.0, 0.0
    d = np.diagonal(sim, offset=lag)
    if d.size == 0:
        return 0.0, 0.0
    return float(np.mean(d)), float(np.mean(d > 0.5))


def best_lag(sim: np.ndarray, start: int, end: int, min_lag: int, max_lag: int) -> list[dict]:
    """Classe les periodes de repetition candidates dans [start, end)."""
    sub = sim[start:end, start:end]
    n = sub.shape[0]
    out = []
    for lag in range(min_lag, min(max_lag, n // 2) + 1):
        mean_sim, coverage = diag_score(sub, lag)
        if mean_sim <= 0.0:
            continue
        bars = lag / 4.0
        out.append(
            {
                "lag_beats": lag,
                "bars": round(bars, 2),
                "mean_similarity": round(mean_sim, 3),
                "coverage": round(coverage, 3),
                "bar_aligned": lag % 4 == 0,
            }
        )
    out.sort(key=lambda item: (item["mean_similarity"], item["coverage"]), reverse=True)
    return out


def best_offset(sim: np.ndarray, start: int, end: int, lag: int) -> tuple[int, float]:
    """Meilleur point de depart d'une boucle de `lag` temps dans [start, end)."""
    best_o, best_score = start, -1.0
    last = end - lag
    for o in range(start, max(start, last)):
        k = min(lag, end - o - lag)
        if k <= 0:
            continue
        idx = o + np.arange(k)
        score = float(np.mean(sim[idx, idx + lag]))
        if score > best_score:
            best_score, best_o = score, o
    return best_o, best_score


def sections_from_novelty(chroma: np.ndarray, min_section_beats: int = 8) -> list[tuple[int, int]]:
    """Detecte les changements de section via une courbe de nouveaute."""
    n = chroma.shape[1]
    window = 4  # une mesure
    if n < 3 * window:
        return [(0, n)]
    novelty = np.zeros(n)
    for t in range(window, n - window):
        a = chroma[:, t - window : t].mean(axis=1)
        b = chroma[:, t : t + window].mean(axis=1)
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na > 1e-9 and nb > 1e-9:
            novelty[t] = 1.0 - float(a @ b / (na * nb))
    peaks, _ = find_peaks(
        novelty,
        distance=max(4, min_section_beats // 2),
        height=max(0.05, float(np.percentile(novelty[novelty > 0], 80))) if np.any(novelty > 0) else 0.05,
    )
    bounds = [0]
    for p in peaks:
        if p - bounds[-1] >= min_section_beats:
            bounds.append(int(p))
    bounds.append(n)
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1) if bounds[i + 1] - bounds[i] >= min_section_beats]


def bar_level(chroma: np.ndarray, n_beats: int) -> tuple[np.ndarray, list[int]]:
    """Chroma moyenne par mesure (4 temps) + index du premier temps de chaque mesure."""
    cols = []
    bar_starts = []
    for b0 in range(0, n_beats - 3, 4):
        vec = chroma[:, b0 : b0 + 4].mean(axis=1)
        norm = float(np.linalg.norm(vec))
        if norm < 1e-9:
            continue
        cols.append(vec / norm)
        bar_starts.append(b0)
    if not cols:
        return np.zeros((12, 0)), []
    return np.asarray(cols).T, bar_starts


def repetition_runs(
    bars: np.ndarray, max_bars: int = 8, threshold: float = 0.75
) -> list[dict]:
    """Trouve les segments de mesures qui se repetent (boucle jouee N fois).

    Pour chaque longueur L (en mesures), on regarde la diagonale decalee de L
    dans la matrice d'auto-similarite des mesures. Un run continu de L
    positions signifie qu'un bloc de L mesures est rejoue au moins 2 fois.
    """
    n_bars = bars.shape[1]
    if n_bars < 2:
        return []
    sim = bars.T @ bars
    runs = []
    for lag in range(1, min(max_bars, n_bars - 1) + 1):
        mask = np.diagonal(sim, offset=lag) > threshold
        i = 0
        while i < len(mask):
            if not mask[i]:
                i += 1
                continue
            j = i
            while j < len(mask) and mask[j]:
                j += 1
            span = j - i  # nombre de positions consecutives
            if span >= lag:  # au moins 2 repetitions completes
                repetitions = 1 + span // lag
                score = float(np.mean(mask[i:j]))
                runs.append(
                    {
                        "length_bars": lag,
                        "repetitions": repetitions,
                        "start_bar": i,
                        "end_bar": i + lag * repetitions,
                        "score": round(score, 3),
                        "span": span,
                    }
                )
            i = j
    # garder le meilleur run par longueur (le plus long puis le meilleur score)
    best: dict[int, dict] = {}
    for run in runs:
        cur = best.get(run["length_bars"])
        key = (run["repetitions"], run["score"])
        if cur is None or key > (cur["repetitions"], cur["score"]):
            best[run["length_bars"]] = run
    return sorted(best.values(), key=lambda r: (r["length_bars"], -r["score"]))


def find_loop_regions(
    bars: np.ndarray, max_bars: int = 8, threshold: float = 0.62, max_regions: int = 3
) -> list[dict]:
    """Extrait les regions ou un bloc de L mesures est rejoue R fois.

    Pour chaque longueur L et chaque depart s, on compare le bloc [s, s+L)
    au bloc suivant [s+L, s+2L), puis au suivant, etc. Une region est retenue
    si chaque repetition depasse le seuil. Les regions ne se chevauchent pas.
    """
    n_bars = bars.shape[1]
    if n_bars < 2:
        return []
    sim = bars.T @ bars
    candidates = []
    for length in range(1, min(max_bars, n_bars // 2) + 1):
        for start in range(n_bars - 2 * length + 1):
            similarities = []
            rep = 0
            while start + (rep + 2) * length <= n_bars:
                a0 = start + rep * length
                b0 = a0 + length
                block = sim[a0 : a0 + length, b0 : b0 + length]
                similarities.append(float(np.mean(np.diagonal(block))))
                rep += 1
            if not similarities or min(similarities) < threshold:
                continue
            repetitions = len(similarities) + 1
            candidates.append(
                {
                    "length_bars": length,
                    "start_bar": start,
                    "end_bar": start + repetitions * length,
                    "repetitions": repetitions,
                    "total_bars": repetitions * length,
                    "score": float(np.mean(similarities)),
                    "min_score": float(np.min(similarities)),
                }
            )
    candidates.sort(
        key=lambda c: (c["total_bars"], c["score"], c["min_score"]), reverse=True
    )
    chosen: list[dict] = []
    occupied = np.zeros(n_bars, dtype=bool)
    for cand in candidates:
        s, e = cand["start_bar"], cand["end_bar"]
        if occupied[s:e].any():
            continue
        chosen.append(cand)
        occupied[s:e] = True
        if len(chosen) >= max_regions:
            break
    return chosen


def fmt_time(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = seconds - minutes * 60
    return f"{minutes}:{secs:05.2f}"


def analyze(path: str, max_bars: int) -> dict:
    y, sr = load_audio(path)
    duration = len(y) / sr
    rms = float(np.sqrt(np.mean(y**2)))
    peak = float(np.max(np.abs(y)))

    sr_a = 22050
    y_a = librosa.resample(y, orig_sr=sr, target_sr=sr_a) if sr != sr_a else y

    hop = 256
    tempo, beats = librosa.beat.beat_track(y=y_a, sr=sr_a, hop_length=hop)
    tempo = float(np.atleast_1d(tempo)[0])
    beat_times = librosa.frames_to_time(beats, sr=sr_a, hop_length=hop)

    result: dict = {
        "path": path,
        "duration_s": round(duration, 2),
        "sample_rate": sr,
        "rms_db": round(20 * np.log10(rms + 1e-12), 2),
        "peak_db": round(20 * np.log10(peak + 1e-12), 2),
        "tempo_bpm": round(tempo, 1),
        "n_beats": len(beat_times),
    }

    if len(beat_times) < 8:
        result["error"] = "trop peu de temps detectes"
        return result

    # chroma par intervalle de temps
    chroma = librosa.feature.chroma_stft(y=y_a, sr=sr_a, hop_length=hop, n_fft=4096)
    frame_bounds = librosa.time_to_frames(beat_times, sr=sr_a, hop_length=hop)
    edges = list(frame_bounds) + [chroma.shape[1]]
    cols = []
    starts = []
    ends = []
    for i in range(len(beat_times)):
        a, b = int(edges[i]), int(edges[i + 1])
        if b <= a:
            continue
        cols.append(np.median(chroma[:, a:b], axis=1))
        starts.append(float(beat_times[i]))
        ends.append(float(beat_times[i + 1]) if i + 1 < len(beat_times) else duration)
    if len(cols) < 8:
        result["error"] = "pas assez d'intervalles de temps exploitables"
        return result

    c = np.asarray(cols).T
    c /= np.linalg.norm(c, axis=0, keepdims=True) + 1e-9
    starts = np.asarray(starts)
    ends = np.asarray(ends)
    n = c.shape[1]

    beat_intervals = np.diff(starts)
    median_beat = float(np.median(beat_intervals))
    result["median_beat_s"] = round(median_beat, 4)
    result["bpm_from_beats"] = round(60.0 / median_beat, 1)
    result["bar_s"] = round(4 * median_beat, 3)

    sim = c.T @ c

    # accords par mesure (groupes de 4 temps)
    bars = []
    for b0 in range(0, n - 3, 4):
        vec = c[:, b0 : b0 + 4].mean(axis=1)
        name, score = chord_from_chroma(vec)
        bars.append(
            {
                "bar": b0 // 4 + 1,
                "t0": round(float(starts[b0]), 2),
                "t1": round(float(ends[min(b0 + 3, n - 1)]), 2),
                "chord": name,
                "confidence": round(score, 2),
            }
        )
    result["bars"] = bars

    # boucles au niveau mesure (un bloc de N mesures rejoue plusieurs fois)
    bar_chroma, bar_starts = bar_level(c, n)
    result["bar_loops"] = []
    for run in repetition_runs(bar_chroma, max_bars=max_bars):
        sb = run["start_bar"]
        eb = min(run["end_bar"], len(bar_starts))
        if sb >= len(bar_starts) or eb <= sb:
            continue
        b0 = bar_starts[sb]
        last_beat = min(bar_starts[eb - 1] + 3, n - 1)
        result["bar_loops"].append(
            {
                "length_bars": run["length_bars"],
                "repetitions": run["repetitions"],
                "score": run["score"],
                "t0": round(float(starts[b0]), 2),
                "t1": round(float(ends[last_beat]), 2),
            }
        )

    # regions ou un bloc de mesures est rejoue plusieurs fois (boucles reelles)
    result["loop_regions"] = []
    for region in find_loop_regions(bar_chroma, max_bars=max_bars):
        s = region["start_bar"]
        e = region["end_bar"]
        if s >= len(bar_starts) or e - 1 >= len(bar_starts):
            continue
        b0 = bar_starts[s]
        last_beat_region = min(bar_starts[e - 1] + 3, n - 1)
        cycle_end_bar = s + region["length_bars"] - 1
        cycle_last_beat = min(bar_starts[cycle_end_bar] + 3, n - 1)
        result["loop_regions"].append(
            {
                "length_bars": region["length_bars"],
                "repetitions": region["repetitions"],
                "score": round(region["score"], 3),
                "min_score": round(region["min_score"], 3),
                "region_t0": round(float(starts[b0]), 2),
                "region_t1": round(float(ends[last_beat_region]), 2),
                "loop_t0": round(float(starts[b0]), 2),
                "loop_t1": round(float(ends[cycle_last_beat]), 2),
            }
        )

    # candidats alignes sur la mesure : pour chaque longueur, le meilleur point
    result["bar_candidates"] = []
    for nb in range(1, max_bars + 1):
        lag = nb * 4
        if lag >= n:
            break
        o, score = best_offset(sim, 0, n, lag)
        if score <= 0:
            continue
        last = min(o + lag - 1, n - 1)
        result["bar_candidates"].append(
            {
                "bars": nb,
                "t0": round(float(starts[o]), 2),
                "t1": round(float(ends[last]), 2),
                "score": round(score, 3),
            }
        )

    # sections
    sections = sections_from_novelty(c)
    result["sections"] = []
    for (s, e) in sections:
        lag_list = best_lag(sim, s, e, min_lag=4, max_lag=max_bars * 4)
        top = lag_list[:3]
        section = {
            "start_beat": s,
            "end_beat": e,
            "t0": round(float(starts[s]), 2),
            "t1": round(float(ends[min(e - 1, n - 1)]), 2),
            "bars": round((e - s) / 4.0, 2),
            "candidates": top,
        }
        if top:
            lag = top[0]["lag_beats"]
            o, score = best_offset(sim, s, e, lag)
            section["loop"] = {
                "start_beat": o,
                "length_beats": lag,
                "bars": round(lag / 4.0, 2),
                "t0": round(float(starts[o]), 2),
                "t1": round(float(ends[min(o + lag - 1, n - 1)]), 2),
                "score": round(score, 3),
            }
        result["sections"].append(section)

    # candidats globaux
    result["global_candidates"] = best_lag(sim, 0, n, min_lag=4, max_lag=max_bars * 4)[:5]
    if result["global_candidates"]:
        lag = result["global_candidates"][0]["lag_beats"]
        o, score = best_offset(sim, 0, n, lag)
        result["global_loop"] = {
            "start_beat": o,
            "length_beats": lag,
            "bars": round(lag / 4.0, 2),
            "t0": round(float(starts[o]), 2),
            "t1": round(float(ends[min(o + lag - 1, n - 1)]), 2),
            "score": round(score, 3),
        }
    return result


def print_report(res: dict) -> None:
    print("=" * 72)
    print("ANALYSE DE BOUCLES")
    print("=" * 72)
    if "error" in res:
        print(f"Erreur : {res['error']}")
        return
    print(f"Fichier      : {res['path']}")
    print(f"Duree        : {fmt_time(res['duration_s'])} ({res['duration_s']} s)")
    print(f"Echantillon. : {res['sample_rate']} Hz")
    print(f"RMS / peak   : {res['rms_db']} dB / {res['peak_db']} dB")
    print(f"Tempo        : {res['tempo_bpm']} BPM (mesure ~{res['bar_s']} s, temps ~{res['median_beat_s']} s)")
    print(f"Temps        : {res['n_beats']}")

    print("\n" + "-" * 72)
    print("ACCORDS PAR MESURE")
    print("-" * 72)
    for bar in res["bars"]:
        print(f"  mesure {bar['bar']:>2}  {bar['t0']:>6.2f}s -> {bar['t1']:>6.2f}s   {bar['chord']:<4} (conf {bar['confidence']})")

    print("\n" + "-" * 72)
    print("BOUCLES AU NIVEAU MESURE (bloc rejoue plusieurs fois)")
    print("-" * 72)
    if not res.get("bar_loops"):
        print("  aucune repetition nette detectee")
    for loop in res.get("bar_loops", []):
        print(
            f"  {loop['length_bars']} mesures x {loop['repetitions']} repetitions "
            f"= {loop['t0']:.2f}s -> {loop['t1']:.2f}s (score {loop['score']})"
        )

    print("\n" + "-" * 72)
    print("BOUCLES REELLES DETECTEES (bloc mesure rejoue)")
    print("-" * 72)
    if not res.get("loop_regions"):
        print("  aucune region repetee nette detectee")
    for i, loop in enumerate(res.get("loop_regions", []), 1):
        print(
            f"  Boucle {i}: {loop['length_bars']} mesure(s) x {loop['repetitions']} repetitions"
        )
        print(
            f"     region jouee : {loop['region_t0']:.2f}s -> {loop['region_t1']:.2f}s "
            f"(sim {loop['score']}, min {loop['min_score']})"
        )
        print(
            f"     a decouper   : {loop['loop_t0']:.2f}s -> {loop['loop_t1']:.2f}s "
            f"({loop['loop_t1'] - loop['loop_t0']:.2f} s)"
        )

    print("\n" + "-" * 72)
    print("CANDIDATS ALIGNES SUR LA MESURE (meilleur point de boucle)")
    print("-" * 72)
    for cand in res.get("bar_candidates", []):
        print(
            f"  {cand['bars']:>2} mesures  {cand['t0']:>6.2f}s -> {cand['t1']:>6.2f}s "
            f"(longueur {cand['t1'] - cand['t0']:.2f}s, score {cand['score']})"
        )

    print("\n" + "-" * 72)
    print("SECTIONS DETECTEES")
    print("-" * 72)
    for i, sec in enumerate(res["sections"], 1):
        print(f"  Section {i}: {sec['t0']:.2f}s -> {sec['t1']:.2f}s  ({sec['bars']} mesures)")
        for cand in sec["candidates"]:
            align = "mesure" if cand["bar_aligned"] else "hors mesure"
            print(
                f"     candidat: {cand['lag_beats']} temps = {cand['bars']} mesures "
                f"({align}) sim={cand['mean_similarity']} cov={cand['coverage']}"
            )
        if "loop" in sec:
            loop = sec["loop"]
            print(
                f"     -> BOUCLE: {loop['t0']:.2f}s -> {loop['t1']:.2f}s "
                f"({loop['bars']} mesures, score {loop['score']})"
            )

    print("\n" + "-" * 72)
    print("MEILLEURE BOUCLE GLOBALE")
    print("-" * 72)
    for cand in res.get("global_candidates", []):
        align = "mesure" if cand["bar_aligned"] else "hors mesure"
        print(
            f"  {cand['lag_beats']} temps = {cand['bars']} mesures ({align}) "
            f"sim={cand['mean_similarity']} cov={cand['coverage']}"
        )
    if "global_loop" in res:
        loop = res["global_loop"]
        print(
            f"\n  => {loop['t0']:.2f}s -> {loop['t1']:.2f}s "
            f"({loop['bars']} mesures, score {loop['score']})"
        )
        print(f"     longueur = {loop['t1'] - loop['t0']:.2f} s")
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description="Detection de boucles dans un WAV")
    parser.add_argument("path")
    parser.add_argument("--max-bars", type=int, default=8, help="longueur max de boucle en mesures (defaut 8)")
    parser.add_argument("--json", action="store_true", help="sortie JSON")
    args = parser.parse_args()

    try:
        res = analyze(args.path, args.max_bars)
    except Exception as exc:  # noqa: BLE001 - CLI
        print(f"Echec de l'analyse : {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print_report(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
