#!/usr/bin/env python
"""DH diagnostic alignment (NO table writes): voice assignment, match rates,
dev medians under BOTH candidate grids (G = canonical written key, A = pitch
of the MIDI / performed edition), written-unison acoustic cross-check."""
import sys, math, json
import numpy as np

sys.path.insert(0, '/private/tmp/claude-501/-Users-sophiegrodin-Desktop/15b0b777-5187-4bcc-b68e-c59553ae8cd8/scratchpad/at-run/code')
from truescore_align import extract_voices_midi, nw_align, hz_to_midi_float, et_hz
from esmuc_v2_build import align_track_drift

ROOT = '/private/tmp/claude-501/-Users-sophiegrodin-Desktop/15b0b777-5187-4bcc-b68e-c59553ae8cd8/scratchpad/at-run'

def main():
    import pandas as pd
    voices_raw = extract_voices_midi(f'{ROOT}/data/scores/WIMA.59ae-die_himmel_erzaehlen.mid')
    # A-pitch (as in MIDI). Keep offsets for ordering info.
    voices = [(n, s, o) for n, s, o in voices_raw]
    print("MIDI voices:", [(n, len(s)) for n, s, o in voices])

    df = pd.read_csv(f'{ROOT}/notes_tables/esmuc_v1_backup.csv')
    dh = df[df.piece_id == 'DH']

    results = []
    assign = {}
    pairs_by_track = {}
    for (take, perf), g in dh.groupby(['take_id', 'performer_id']):
        g = g.sort_values('note_idx')
        pm = np.array([
            hz_to_midi_float(r.f0_median_hz_best) if r.f0_median_hz_best == r.f0_median_hz_best else
            (hz_to_midi_float(r.f0_median_hz_uniform) if r.f0_median_hz_uniform == r.f0_median_hz_uniform else float(r.score_midi))
            for r in g.itertuples()])
        onsets = g.onset_sec.to_numpy()
        best = None
        for vi, (vname, vseq, voffs) in enumerate(voices):
            res = align_track_drift(pm, onsets, vseq)
            matched = sum(1 for j in res['pairs'] if j is not None)
            cpn = res['cost2'] / len(pm)
            if best is None or cpn < best['cpn']:
                best = dict(vi=vi, vname=vname, cpn=cpn, res=res, matched=matched, vseq=vseq)
        res = best['res']
        pairs = res['pairs']
        vseq = best['vseq']
        v1m = g.score_midi.to_numpy(int)
        # labels under A grid (midi as-is) and G grid (midi-2)
        agreeA = sum(1 for i, j in enumerate(pairs) if j is not None and vseq[j] == v1m[i])
        agreeG = sum(1 for i, j in enumerate(pairs) if j is not None and vseq[j] - 2 == v1m[i])
        # dev medians (best pipeline) under both grids
        devA, devG = [], []
        for i, (j, r) in enumerate(zip(pairs, g.itertuples())):
            if j is None or not (r.f0_median_hz_best == r.f0_median_hz_best):
                continue
            devA.append(1200 * math.log2(r.f0_median_hz_best / et_hz(vseq[j])))
            devG.append(1200 * math.log2(r.f0_median_hz_best / et_hz(vseq[j] - 2)))
        pairs_by_track[(take, perf)] = (g.index.to_numpy(), pairs, vseq)
        assign[(take, perf)] = best['vname']
        results.append(dict(
            take=take, perf=perf, voice=best['vname'], cpn=round(best['cpn'], 3),
            matched=best['matched'], n_perf=len(pm),
            unm=len(pm) - best['matched'],
            k_contour=res['k_contour'],
            agreeA=round(agreeA / best['matched'], 3),
            agreeG=round(agreeG / best['matched'], 3),
            devA_med=round(float(np.median(devA)), 1),
            devG_med=round(float(np.median(devG)), 1),
            drift0=round(100 * res['drift'][0], 0), drift1=round(100 * res['drift'][-1], 0)))

    for r in results:
        print(f"{r['take']} {r['perf']}: voice={r['voice']:<9} match {r['matched']}/{r['n_perf']} "
              f"cpn={r['cpn']} k={r['k_contour']} agree_v1(Agrid)={r['agreeA']} (Ggrid)={r['agreeG']} "
              f"devmedA={r['devA_med']}c devmedG={r['devG_med']}c drift(A) {r['drift0']}->{r['drift1']}c")

    # -------- written-unison/octave acoustic cross-check --------
    # pairs of simultaneous notes in different tracks whose ALIGNED written
    # pitches are equal mod 12; compare sung interval to written interval.
    lab = {}
    for (take, perf), (idx, pairs, vseq) in pairs_by_track.items():
        for i, j in enumerate(pairs):
            if j is not None:
                lab[idx[i]] = vseq[j]   # A-grid written pitch (grid-independent for intervals)
    err = []
    for take, g in dh.groupby('take_id'):
        g = g[g.f0_median_hz_best.notna()]
        rows = [r for r in g.itertuples() if r.Index in lab]
        rows.sort(key=lambda r: r.onset_sec)
        for a in range(len(rows)):
            ra = rows[a]
            mida = (ra.onset_sec + ra.offset_sec) / 2
            for b in range(a + 1, len(rows)):
                rb = rows[b]
                if rb.onset_sec > mida:
                    break
                if rb.performer_id == ra.performer_id:
                    continue
                if not (rb.onset_sec <= mida and rb.offset_sec > mida):
                    continue
                w = lab[ra.Index] - lab[rb.Index]
                if w % 12 == 0:
                    sung = 1200 * math.log2(ra.f0_median_hz_best / rb.f0_median_hz_best)
                    err.append(sung - 100 * w)
    err = np.array(err)
    print(f"\nUNISON/OCTAVE CROSS-CHECK: n={len(err)} pairs | median={np.median(err):.1f}c "
          f"IQR=[{np.percentile(err,25):.1f},{np.percentile(err,75):.1f}] "
          f"|err|>200c: {(np.abs(err)>200).sum()} ({100*(np.abs(err)>200).mean():.1f}%)")

    json.dump(dict(tracks=results, unison_n=int(len(err)),
                   unison_median=float(np.median(err)),
                   unison_q25=float(np.percentile(err, 25)),
                   unison_q75=float(np.percentile(err, 75)),
                   unison_gt200=int((np.abs(err) > 200).sum())),
              open(f'{ROOT}/logs/dh_diagnostic.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
