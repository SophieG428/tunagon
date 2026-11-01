#!/usr/bin/env python
"""ESMUC v2 true-score alignment library.

Parses public-domain scores (MusicXML/MIDI), extracts per-voice note sequences,
and aligns each ESMUC performed track (ordered notes from notes_tables/esmuc.csv)
to the best-matching score voice with a semi-global Needleman-Wunsch on pitch
(octave-tolerant, global integer transposition estimated per track).
"""
import json
import math
import numpy as np


def hz_to_midi_float(hz):
    return 69.0 + 12.0 * math.log2(hz / 440.0)


def et_hz(m):
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


def extract_voices_music21(path, exclude_part_substrings=("piano", "continuo", "organ", "bc")):
    """Return list of (voice_name, [midi,...], [offset_qn,...]) in score order, vocal parts only."""
    import music21
    s = music21.converter.parse(path)
    try:
        s2 = s.expandRepeats()
    except Exception:
        s2 = s
    out = []
    for p in s2.parts:
        name = (p.partName or str(p.id) or "?")
        if any(x in name.lower() for x in exclude_part_substrings):
            continue
        pf = p.flatten().stripTies()
        seq, offs = [], []
        for n in pf.notes:
            if getattr(n.duration, "isGrace", False):
                continue
            if n.isChord:
                # vocal part chord = divisi; take all pitches at same offset (rare)
                for pp in sorted(n.pitches, key=lambda q: q.midi):
                    seq.append(pp.midi)
                    offs.append(float(n.offset))
            else:
                seq.append(n.pitch.midi)
                offs.append(float(n.offset))
        if seq:
            out.append((name, seq, offs))
    return out


def extract_voices_midi(path):
    """Per-track monophonic-ish note sequences from a MIDI file via music21."""
    import music21
    s = music21.converter.parse(path)
    out = []
    for p in s.parts:
        name = (p.partName or str(p.id) or "?")
        pf = p.flatten().stripTies()
        seq, offs = [], []
        for n in pf.notes:
            if n.isChord:
                for pp in sorted(n.pitches, key=lambda q: q.midi):
                    seq.append(pp.midi)
                    offs.append(float(n.offset))
            else:
                seq.append(n.pitch.midi)
                offs.append(float(n.offset))
        if seq:
            out.append((name, seq, offs))
    return out


def nw_align(perf, score, gap_perf=2.0, gap_score=0.9, cap=3.0, semi_global=True):
    """Semi-global NW: perf (floats, len n) vs score (ints, len m).
    Free leading/trailing gaps in SCORE (performance may be an excerpt).
    Returns (total_cost, pairs) where pairs[i] = score index j or None per perf note.
    """
    n, m = len(perf), len(score)
    INF = 1e18
    D = np.full((n + 1, m + 1), INF)
    B = np.zeros((n + 1, m + 1), dtype=np.int8)  # 0 diag, 1 up (gap perf), 2 left (gap score)
    D[0, :] = 0.0 if semi_global else np.arange(m + 1) * gap_score
    D[0, 0] = 0.0
    for i in range(1, n + 1):
        D[i, 0] = D[i - 1, 0] + gap_perf
        B[i, 0] = 1
    perf = np.asarray(perf, dtype=float)
    score_arr = np.asarray(score, dtype=float)
    for i in range(1, n + 1):
        # vectorized row
        diffs = np.abs(perf[i - 1] - score_arr)  # len m
        sub = np.minimum(diffs, cap)
        diag = D[i - 1, :m] + sub
        up = D[i - 1, 1:] + gap_perf
        row = D[i]
        prev_best = INF
        # need left dependency -> sequential, but diag/up precomputed
        left_pen = gap_score
        for j in range(1, m + 1):
            d = diag[j - 1]
            u = up[j - 1]
            l = row[j - 1] + left_pen
            if d <= u and d <= l:
                row[j] = d
                B[i, j] = 0
            elif l <= u:
                row[j] = l
                B[i, j] = 2
            else:
                row[j] = u
                B[i, j] = 1
    # terminal: free trailing score gaps -> best over last row
    if semi_global:
        jend = int(np.argmin(D[n, :]))
        total = float(D[n, jend])
    else:
        jend = m
        total = float(D[n, m])
    pairs = [None] * n
    i, j = n, jend
    while i > 0:
        b = B[i, j]
        if b == 0:
            pairs[i - 1] = j - 1
            i -= 1
            j -= 1
        elif b == 1:
            pairs[i - 1] = None
            i -= 1
        else:
            j -= 1
    return total, pairs


def align_track(perf_midi_float, voices, k_extra=(-1, 0, 1), **nw_kw):
    """Try every score voice x global transposition; return best.
    Returns dict with voice_idx, voice_name, k, cost_per_note, pairs.
    """
    best = None
    pm = np.asarray(perf_midi_float, dtype=float)
    for vi, (vname, vseq, voffs) in enumerate(voices):
        varr = np.asarray(vseq, dtype=float)
        k0 = int(round(np.median(pm) - np.median(varr)))
        for dk in k_extra:
            k = k0 + dk
            cost, pairs = nw_align(pm - k, vseq, **nw_kw)
            matched = sum(1 for p in pairs if p is not None)
            if matched == 0:
                continue
            cpn = cost / len(pm)
            if best is None or cpn < best["cost_per_note"]:
                best = dict(voice_idx=vi, voice_name=vname, k=k,
                            cost_per_note=cpn, cost=cost, pairs=pairs,
                            n_perf=len(pm), n_score=len(vseq),
                            n_matched=matched)
    return best
