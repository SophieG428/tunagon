#!/usr/bin/env python
"""ESMUC v2: replace reconstructed score_midi with true score pitches for DG
(Haydn, Der Greis, CPDL #17663 MusicXML), rebuild dependent columns.

Alignment: 2-pass drift-adaptive semi-global Needleman-Wunsch per track.
Labels use the score AS WRITTEN (A major); no re-anchoring (contract).
Rows of other pieces are preserved byte-identically (string-level edit).
"""
import csv
import json
import math
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, '/private/tmp/claude-501/-Users-sophiegrodin-Desktop/15b0b777-5187-4bcc-b68e-c59553ae8cd8/scratchpad/at-run/code')
from truescore_align import extract_voices_music21, nw_align, hz_to_midi_float, et_hz

ROOT = '/private/tmp/claude-501/-Users-sophiegrodin-Desktop/15b0b777-5187-4bcc-b68e-c59553ae8cd8/scratchpad/at-run'
CSV = f'{ROOT}/notes_tables/esmuc.csv'
BACKUP = f'{ROOT}/notes_tables/esmuc_v1_backup.csv'
SEED = 20260813

PART2VOICE = {'S': 'Soprano', 'A': 'Alto', 'T': 'Tenore', 'B': 'Basso'}


def dev_cents(f0, m):
    return 1200.0 * math.log2(f0 / et_hz(m))


def running_median_drift(times, resid, win=10):
    """Running median of residuals (semitone units) over +-win matched notes."""
    order = np.argsort(times)
    t_s, r_s = np.asarray(times)[order], np.asarray(resid)[order]
    d = np.empty(len(t_s))
    for p in range(len(t_s)):
        lo, hi = max(0, p - win), min(len(t_s), p + win + 1)
        d[p] = np.median(r_s[lo:hi])
    return t_s, d


def align_track_drift(pm, onsets, vseq, k0_range=(-2, -1, 0, 1, 2)):
    """2-pass drift-adaptive alignment of perf (float midi pm) vs score vseq.
    Returns dict(pairs, k_contour, drift_at_note, pass1_pairs)."""
    pm = np.asarray(pm, float)
    # pass 1: global k on contour
    best = None
    k0 = int(round(np.median(pm) - np.median(vseq)))
    for dk in k0_range:
        k = k0 + dk
        cost, pairs = nw_align(pm - k, vseq, gap_perf=2.0, gap_score=0.9, cap=3.0)
        if best is None or cost < best[0]:
            best = (cost, pairs, k)
    _, pairs1, k1 = best
    # drift curve from pass-1 matches, relative to WRITTEN score
    mt = [onsets[i] for i, j in enumerate(pairs1) if j is not None]
    mr = [pm[i] - vseq[j] for i, j in enumerate(pairs1) if j is not None]
    t_s, d_s = running_median_drift(mt, mr, win=10)
    drift = np.interp(onsets, t_s, d_s)
    # pass 2: drift-corrected absolute-pitch alignment (k absorbed by drift)
    cost2, pairs2 = nw_align(pm - drift, vseq, gap_perf=2.0, gap_score=0.9, cap=2.0)
    return dict(pairs=pairs2, k_contour=k1, drift=drift, pairs1=pairs1, cost2=cost2)


def main():
    import pandas as pd
    # ---------- load ----------
    voices_raw = extract_voices_music21(f'{ROOT}/data/scores/Hayd-dergreis.mxl')
    voices = {name: seq for name, seq, offs in voices_raw}
    df = pd.read_csv(CSV)

    rows_str = list(csv.reader(open(CSV, newline='', encoding='utf-8')))
    header, data = rows_str[0], rows_str[1:]
    col = {c: i for i, c in enumerate(header)}
    assert len(data) == len(df)

    dg_mask = df.piece_id == 'DG'
    report = {'tracks': [], 'notes_changed': 0, 'delta_hist': defaultdict(int)}
    new_midi = {}          # row index -> new score_midi (int)
    unmatched_rows = []    # row indices kept at v1 label

    # ---------- align every DG track ----------
    for (take, perf), g in df[dg_mask].groupby(['take_id', 'performer_id']):
        g = g.sort_values('note_idx')
        idx = g.index.to_numpy()
        pm = np.array([
            hz_to_midi_float(r.f0_median_hz_best) if r.f0_median_hz_best == r.f0_median_hz_best and r.f0_median_hz_best > 0
            else (hz_to_midi_float(r.f0_median_hz_uniform) if r.f0_median_hz_uniform == r.f0_median_hz_uniform and r.f0_median_hz_uniform > 0
                  else float(r.score_midi))
            for r in g.itertuples()])
        onsets = g.onset_sec.to_numpy()
        vseq = voices[PART2VOICE[g.part.iloc[0]]]
        res = align_track_drift(pm, onsets, vseq)
        pairs = res['pairs']
        v1m = g.score_midi.to_numpy(int)
        n_match = sum(1 for j in pairs if j is not None)
        n_un = len(pairs) - n_match
        n_skip = len(vseq) - len({j for j in pairs if j is not None})
        agree = equal = w50_ok = w50_tot = 0
        deltas = []
        for i, j in enumerate(pairs):
            ri = idx[i]
            if j is None:
                unmatched_rows.append(ri)
                continue
            s = int(vseq[j])
            new_midi[ri] = s
            if s == v1m[i]:
                equal += 1
            else:
                deltas.append(v1m[i] - s)
                report['delta_hist'][v1m[i] - s] += 1
            # contract-expectation check: v1 right when singer within 50c of true pitch
            if abs(pm[i] - s) < 0.5:
                w50_tot += 1
                w50_ok += (int(round(pm[i])) == s == v1m[i])
        pairs_changed = sum(1 for a, b in zip(res['pairs1'], pairs) if a != b)
        report['tracks'].append(dict(
            take=take, perf=perf, part=g.part.iloc[0], n_perf=len(pm),
            n_score=len(vseq), matched=n_match, unmatched_perf=n_un,
            skipped_score=n_skip, agree_v1=equal / n_match,
            k_contour=res['k_contour'],
            drift_start_c=100 * res['drift'][0], drift_end_c=100 * res['drift'][-1],
            within50_consistent=(w50_ok, w50_tot),
            pass_delta=pairs_changed))
        report['notes_changed'] += len(deltas)

    # ---------- rebuild DG rows (string level) ----------
    df2 = df.copy()
    for ri, m in new_midi.items():
        df2.at[ri, 'score_midi'] = m

    # concurrent + bass per DG take from NEW midi, shipped spans
    conc_json = {}
    bass_new = {}
    for take, g in df2[dg_mask].groupby('take_id'):
        on, off = g.onset_sec.to_numpy(), g.offset_sec.to_numpy()
        mi = g.score_midi.to_numpy(int)
        parts = g.part.to_numpy()
        idx = g.index.to_numpy()
        for a in range(len(idx)):
            mid = (on[a] + off[a]) / 2
            mask = (parts != parts[a]) & (on <= mid) & (off > mid)
            conc = sorted(set(mi[mask].tolist()))
            conc_json[idx[a]] = json.dumps(conc)
            bass_new[idx[a]] = min(conc + [int(mi[a])])

    # devs from new reference
    dev_b = {}
    dev_u = {}
    for r in df2[dg_mask].itertuples():
        if r.f0_median_hz_best == r.f0_median_hz_best:
            dev_b[r.Index] = round(dev_cents(r.f0_median_hz_best, r.score_midi), 2)
        if r.f0_median_hz_uniform == r.f0_median_hz_uniform:
            dev_u[r.Index] = round(dev_cents(r.f0_median_hz_uniform, r.score_midi), 2)

    # suspect_octave for DG tracks from new devs (exclude-self window, OR of pipelines)
    def flags_for(devs):
        out = np.zeros(len(devs), bool)
        vidx = np.where(~np.isnan(devs))[0]
        vdev = devs[vidx]
        for p, i in enumerate(vidx):
            lo, hi = max(0, p - 8), min(len(vidx), p + 9)
            win = np.concatenate([vdev[lo:p], vdev[p + 1:hi]])
            if len(win) and abs(vdev[p] - np.median(win)) > 600:
                out[i] = True
        return out

    sus = {}
    for (take, perf), g in df2[dg_mask].groupby(['take_id', 'performer_id']):
        g = g.sort_values('note_idx')
        db = np.array([dev_b.get(i, np.nan) for i in g.index], float)
        du = np.array([dev_u.get(i, np.nan) for i in g.index], float)
        f = flags_for(db) | flags_for(du)
        for i, fi in zip(g.index, f):
            sus[i] = int(fi)

    # ---------- write: edit only DG rows as strings ----------
    import os
    import shutil
    if not os.path.exists(BACKUP):
        shutil.copyfile(CSV, BACKUP)
    dg_rows = set(df.index[dg_mask])
    for ri in dg_rows:
        row = data[ri]
        row[col['score_midi']] = str(int(df2.at[ri, 'score_midi']))
        row[col['dev_cents_best']] = str(dev_b[ri]) if ri in dev_b else ''
        row[col['dev_cents_uniform']] = str(dev_u[ri]) if ri in dev_u else ''
        row[col['concurrent_midi_json']] = conc_json[ri]
        row[col['bass_midi']] = str(bass_new[ri])
        row[col['suspect_octave_flag']] = str(sus[ri])
    with open(CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(data)

    # ---------- report ----------
    out = dict(report=report['tracks'],
               notes_changed=report['notes_changed'],
               delta_hist={int(k): int(v) for k, v in report['delta_hist'].items()},
               n_unmatched_total=len(unmatched_rows),
               unmatched_rows=[int(r) for r in unmatched_rows])
    with open(f'{ROOT}/logs/esmuc_v2_align_report.json', 'w') as f:
        json.dump(out, f, indent=1, default=str)
    print("tracks aligned:", len(report['tracks']))
    print("labels changed:", report['notes_changed'])
    print("delta hist (v1 - new):", dict(report['delta_hist']))
    print("unmatched perf notes (kept v1):", len(unmatched_rows))
    for t in report['tracks']:
        print(f"{t['take']} {t['perf']}: match {t['matched']}/{t['n_perf']} "
              f"agree_v1={t['agree_v1']:.3f} k={t['k_contour']} "
              f"drift {t['drift_start_c']:.0f}c -> {t['drift_end_c']:.0f}c "
              f"skip={t['skipped_score']} unm={t['unmatched_perf']} "
              f"w50={t['within50_consistent']} pass_delta={t['pass_delta']}")


if __name__ == '__main__':
    main()
