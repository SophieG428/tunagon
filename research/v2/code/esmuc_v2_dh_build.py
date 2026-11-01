#!/usr/bin/env python
"""ESMUC v2 DH rebuild: true score pitches from the Alpers SWV 386 MIDI,
A grid (transpose 0) per coordinator decision 2026-10-07.
Edits DH rows ONLY (string level); DG/SC byte-identical. Applies contract
v1.2 (|dev|>300c vs own pitch, either pipeline, unrounded) to DH rows,
in addition to the v1.0 running-median rule."""
import csv
import json
import math
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, '/private/tmp/claude-501/-Users-sophiegrodin-Desktop/15b0b777-5187-4bcc-b68e-c59553ae8cd8/scratchpad/at-run/code')
from truescore_align import extract_voices_midi, hz_to_midi_float, et_hz
from esmuc_v2_build import align_track_drift

ROOT = '/private/tmp/claude-501/-Users-sophiegrodin-Desktop/15b0b777-5187-4bcc-b68e-c59553ae8cd8/scratchpad/at-run'
CSV = f'{ROOT}/notes_tables/esmuc.csv'
TRANSPOSE = 0  # A grid (performed edition), coordinator decision 2026-10-07


def dev_cents(f0, m):
    return 1200.0 * math.log2(f0 / et_hz(m))


def main():
    import pandas as pd
    voices = [(n, [p + TRANSPOSE for p in s], o)
              for n, s, o in extract_voices_midi(f'{ROOT}/data/scores/WIMA.59ae-die_himmel_erzaehlen.mid')]
    df = pd.read_csv(CSV)
    rows_str = list(csv.reader(open(CSV, newline='', encoding='utf-8')))
    header, data = rows_str[0], rows_str[1:]
    col = {c: i for i, c in enumerate(header)}
    dh_mask = df.piece_id == 'DH'

    new_midi = {}
    unmatched_rows = []
    track_rep = []
    delta_hist = defaultdict(int)
    assign = {}

    for (take, perf), g in df[dh_mask].groupby(['take_id', 'performer_id']):
        g = g.sort_values('note_idx')
        idx = g.index.to_numpy()
        pm = np.array([
            hz_to_midi_float(r.f0_median_hz_best) if r.f0_median_hz_best == r.f0_median_hz_best else
            (hz_to_midi_float(r.f0_median_hz_uniform) if r.f0_median_hz_uniform == r.f0_median_hz_uniform else float(r.score_midi))
            for r in g.itertuples()])
        onsets = g.onset_sec.to_numpy()
        best = None
        for vi, (vname, vseq, voffs) in enumerate(voices):
            res = align_track_drift(pm, onsets, vseq)
            cpn = res['cost2'] / len(pm)
            if best is None or cpn < best['cpn']:
                best = dict(vname=vname, vseq=vseq, res=res, cpn=cpn)
        pairs = best['res']['pairs']
        vseq = best['vseq']
        assign[(take, perf)] = best['vname']
        v1m = g.score_midi.to_numpy(int)
        equal = 0
        for i, j in enumerate(pairs):
            if j is None:
                unmatched_rows.append(int(idx[i]))
                continue
            s = int(vseq[j])
            new_midi[idx[i]] = s
            if s == v1m[i]:
                equal += 1
            else:
                delta_hist[int(v1m[i] - s)] += 1
        matched = sum(1 for j in pairs if j is not None)
        track_rep.append(dict(
            take=take, perf=perf, voice=best['vname'], n_perf=len(pm),
            matched=matched, unmatched=len(pm) - matched,
            agree_v1=round(equal / matched, 3), k_contour=best['res']['k_contour'],
            drift_start_c=round(100 * best['res']['drift'][0]),
            drift_end_c=round(100 * best['res']['drift'][-1])))

    df2 = df.copy()
    for ri, m in new_midi.items():
        df2.at[ri, 'score_midi'] = m

    # concurrent + bass per DH take (v1 rule: other S/A/T/B parts, shipped spans)
    conc_json, bass_new = {}, {}
    for take, g in df2[dh_mask].groupby('take_id'):
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

    # devs (unrounded kept for flag pass)
    devb_u, devu_u = {}, {}
    for r in df2[dh_mask].itertuples():
        if r.f0_median_hz_best == r.f0_median_hz_best:
            devb_u[r.Index] = dev_cents(r.f0_median_hz_best, r.score_midi)
        if r.f0_median_hz_uniform == r.f0_median_hz_uniform:
            devu_u[r.Index] = dev_cents(r.f0_median_hz_uniform, r.score_midi)

    # suspect_octave: v1.0 running-median (exclude-self +-8 valid) OR v1.2 |dev|>300
    def flags_runmed(devs):
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
    n_v12_only = 0
    for (take, perf), g in df2[dh_mask].groupby(['take_id', 'performer_id']):
        g = g.sort_values('note_idx')
        db = np.array([devb_u.get(i, np.nan) for i in g.index], float)
        du = np.array([devu_u.get(i, np.nan) for i in g.index], float)
        f_rm = flags_runmed(db) | flags_runmed(du)
        f_12 = (np.abs(np.nan_to_num(db)) > 300) & ~np.isnan(db) | ((np.abs(np.nan_to_num(du)) > 300) & ~np.isnan(du))
        n_v12_only += int((f_12 & ~f_rm).sum())
        f = f_rm | f_12
        for i, fi in zip(g.index, f):
            sus[i] = int(fi)

    # write DH rows only
    dh_rows = set(df.index[dh_mask])
    for ri in dh_rows:
        row = data[ri]
        row[col['score_midi']] = str(int(df2.at[ri, 'score_midi']))
        row[col['dev_cents_best']] = str(round(devb_u[ri], 2)) if ri in devb_u else ''
        row[col['dev_cents_uniform']] = str(round(devu_u[ri], 2)) if ri in devu_u else ''
        row[col['concurrent_midi_json']] = conc_json[ri]
        row[col['bass_midi']] = str(bass_new[ri])
        row[col['suspect_octave_flag']] = str(sus[ri])
    with open(CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(data)

    out = dict(decision='A grid (transpose 0), coordinator 2026-10-07',
               tracks=track_rep,
               voice_assignment={f"{k[0]}|{k[1]}": v for k, v in assign.items()},
               notes_changed=sum(delta_hist.values()),
               delta_hist={int(k): int(v) for k, v in delta_hist.items()},
               n_unmatched=len(unmatched_rows), unmatched_rows=unmatched_rows,
               suspect_flags_dh=int(sum(sus.values())), v12_only_flags=n_v12_only)
    rep = json.load(open(f'{ROOT}/logs/esmuc_v2_align_report.json'))
    rep['dh_rebuild_2026-10-07'] = out
    json.dump(rep, open(f'{ROOT}/logs/esmuc_v2_align_report.json', 'w'), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k not in ('tracks', 'unmatched_rows', 'voice_assignment')}, indent=1))
    for t in track_rep:
        print(f"{t['take']} {t['perf']}: {t['voice']:<9} match {t['matched']}/{t['n_perf']} "
              f"agree_v1={t['agree_v1']} drift {t['drift_start_c']}->{t['drift_end_c']}c")


if __name__ == '__main__':
    main()
