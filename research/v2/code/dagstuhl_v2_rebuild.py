#!/usr/bin/env python
"""Dagstuhl v2: re-extract the UNIFORM label pipeline with our own pYIN
(contract v1.1 spec) and rebuild only the uniform columns + flags of
notes_tables/dagstuhl.csv. Best-pipeline columns and all other fields are
kept byte-identical via right-split line surgery.

Stages:
  1. backup old uniform columns
  2. pyin extraction (108 tracks, ProcessPoolExecutor, max 10 workers)
  3. per-note uniform labels (15% trim, >=5 voiced frames)
  4. flags: short_note = OR(best-side from table, new uniform-side);
     suspect_octave = OR(best-side recomputed from table devs, new uniform-side)
     -- the octave-rule implementation is first VALIDATED by reproducing the
     v1 flag column from the old table's own dev columns.
  5. sidecar npz (uniform pipeline) to sidecar_frames/dagstuhl/
  6. CSV rewrite with byte-identity verification of untouched fields
  7. stats + self-check printed to stdout
"""
import csv, json, math, os, sys, time
import numpy as np

ROOT = "/private/tmp/claude-501/-Users-sophiegrodin-Desktop/15b0b777-5187-4bcc-b68e-c59553ae8cd8/scratchpad/at-run"
CSV_PATH = os.path.join(ROOT, "notes_tables", "dagstuhl.csv")
BACKUP = os.path.join(ROOT, "notes_tables", "dagstuhl_v1_uniform_backup.csv")
TRACK_MAP = os.path.join(ROOT, "code", "dagstuhl_v2_track_map.json")
STASH_AUDIO = os.path.join(ROOT, "data", "Dagstuhl ChoirSet",
                           "DagstuhlChoirSet_V1.2.2", "audio_wav_22050_mono")
SIDE_DIR = os.path.join(ROOT, "sidecar_frames", "dagstuhl")
SEED = 20260813
SR = 22050
HOP = 256
FRAME_LENGTH = 2048
RESOLUTION = 0.05
FMINMAX = {"S": (180.0, 1200.0), "A": (130.0, 800.0),
           "T": (90.0, 600.0), "B": (55.0, 400.0)}
N_WORKERS = 10

EXPECTED_HEADER = ("dataset,piece_id,take_id,performer_id,part,instrument,note_idx,"
                   "score_midi,onset_sec,offset_sec,duration_sec,"
                   "concurrent_midi_json,bass_midi,is_open_string,"
                   "f0_median_hz_uniform,dev_cents_uniform,n_kept_uniform,"
                   "voiced_pct_uniform,label_source_uniform,"
                   "f0_median_hz_best,dev_cents_best,n_kept_best,voiced_pct_best,"
                   "label_source_best,onset_refined_ms,short_note_flag,"
                   "suspect_octave_flag,is_control")


def et_hz(m):
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


def extract_track(args):
    """Worker: load wav, run contract-spec pyin, return voiced frames."""
    key, wav, part = args
    import librosa  # import inside worker (spawn)
    fmin, fmax = FMINMAX[part]
    t0 = time.time()
    y, sr = librosa.load(wav, sr=SR, mono=True)
    f0, voiced_flag, voiced_prob = librosa.pyin(
        y, fmin=fmin, fmax=fmax, sr=SR,
        frame_length=FRAME_LENGTH, hop_length=HOP,
        center=True, resolution=RESOLUTION)
    n_frames = len(f0)
    voiced = voiced_flag & ~np.isnan(f0)
    times = librosa.times_like(f0, sr=SR, hop_length=HOP)
    return (key, n_frames, times[voiced].astype(np.float64),
            f0[voiced].astype(np.float64), time.time() - t0, len(y) / SR)


def runmed_octave_flags(devs):
    """Contract octave QC: for each valid note (devs = list in note order),
    running median over the +-8 NEIGHBORING valid notes (self EXCLUDED --
    this variant reproduces v1's flag column exactly: 263 flags, 0 mismatches);
    flag |dev - median| > 600 cents. Returns list of 0/1."""
    n = len(devs)
    out = [0] * n
    arr = np.asarray(devs, dtype=float)
    for i in range(n):
        lo, hi = max(0, i - 8), min(n, i + 9)
        w = np.concatenate([arr[lo:i], arr[i + 1:hi]])
        if len(w) == 0:
            continue
        if abs(arr[i] - np.median(w)) > 600.0:
            out[i] = 1
    return out


def flags_for_column(rows, ix, col):
    """Recompute octave flags per track from an existing dev column.
    Returns dict row_index -> 0/1 (0 for invalid rows)."""
    from collections import defaultdict
    by_track = defaultdict(list)  # key -> list of (row_i, dev)
    for i, r in enumerate(rows):
        key = r[ix["take_id"]] + "_" + r[ix["performer_id"]]
        v = r[ix[col]]
        if v != "":
            by_track[key].append((i, float(v)))
    flags = {}
    for key, pairs in by_track.items():
        pairs.sort(key=lambda p: p[0])  # rows are in note_idx order per track
        fl = runmed_octave_flags([d for _, d in pairs])
        for (i, _), f in zip(pairs, fl):
            flags[i] = f
    return flags


def main():
    t_start = time.time()
    # ---------- load table ----------
    raw_lines = open(CSV_PATH, "r", encoding="utf-8").read().splitlines()
    header = raw_lines[0]
    assert header == EXPECTED_HEADER, "schema mismatch before rebuild"
    data_lines = raw_lines[1:]
    rows = list(csv.reader(data_lines))
    hdr = header.split(",")  # safe: header has no quoted fields
    ix = {c: i for i, c in enumerate(hdr)}
    assert len(rows) == 9730, f"row count {len(rows)}"

    track_map = json.load(open(TRACK_MAP))
    assert len(track_map) == 108

    # ---------- 1. backup old uniform columns ----------
    bcols = ["dataset", "piece_id", "take_id", "performer_id", "part", "note_idx",
             "f0_median_hz_uniform", "dev_cents_uniform", "n_kept_uniform",
             "voiced_pct_uniform", "label_source_uniform",
             "short_note_flag", "suspect_octave_flag"]
    with open(BACKUP, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(bcols)
        for r in rows:
            w.writerow([r[ix[c]] for c in bcols])
    print(f"backup written: {BACKUP} ({len(rows)} rows)")

    # ---------- validate octave-rule implementation against v1 ----------
    fl_u_old = flags_for_column(rows, ix, "dev_cents_uniform")
    fl_b = flags_for_column(rows, ix, "dev_cents_best")
    mismatch = 0
    n_flag_old = 0
    for i, r in enumerate(rows):
        pred = 1 if (fl_u_old.get(i, 0) or fl_b.get(i, 0)) else 0
        old = int(r[ix["suspect_octave_flag"]])
        n_flag_old += old
        if pred != old:
            mismatch += 1
    print(f"octave-rule validation vs v1 column: {mismatch} mismatches "
          f"(v1 flags={n_flag_old}, recomputed OR={sum(1 for i in range(len(rows)) if fl_u_old.get(i,0) or fl_b.get(i,0))})")
    if mismatch != 0:
        print("WARNING: running-median variant does not reproduce v1 exactly")

    # validate short-note semantics vs v1
    sn_pred = sum(1 for r in rows if
                  (r[ix["label_source_uniform"]] != "" and r[ix["f0_median_hz_uniform"]] == "")
                  or r[ix["f0_median_hz_best"]] == "")
    sn_old = sum(int(r[ix["short_note_flag"]]) for r in rows)
    print(f"short-note semantics validation: predicted {sn_pred}, v1 column {sn_old}")

    # ---------- 2. pyin extraction ----------
    jobs = []
    for key, t in sorted(track_map.items()):
        wav = os.path.join(STASH_AUDIO, t["wav"])
        assert os.path.exists(wav), wav
        jobs.append((key, wav, t["part"]))

    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    from concurrent.futures import ProcessPoolExecutor, as_completed
    track_frames = {}
    audio_secs = 0.0
    t_ext = time.time()
    with ProcessPoolExecutor(max_workers=N_WORKERS) as pool:
        futs = {pool.submit(extract_track, j): j[0] for j in jobs}
        done = 0
        for fut in as_completed(futs):
            key, n_frames, vt, vf, dt, dur = fut.result()
            track_frames[key] = (n_frames, vt, vf)
            audio_secs += dur
            done += 1
            if done % 12 == 0 or done == len(jobs):
                print(f"  pyin {done}/{len(jobs)} (last {key}: {dur:.0f}s audio, {dt:.0f}s cpu)", flush=True)
    ext_wall = time.time() - t_ext
    print(f"extraction done: {len(track_frames)} tracks, {audio_secs/60:.1f} min audio, "
          f"{ext_wall/60:.1f} min wall")

    # ---------- 3. per-note uniform labels ----------
    new_u = {}       # row index -> (f0_str, dev_str, nkept_str, pct_str, src)
    sidecar = {}     # key -> {note_idx: (t_arr, f_arr)}
    new_valid = {}   # row index -> dev float (valid only)
    n_short_u_new = 0
    for i, r in enumerate(rows):
        key = r[ix["take_id"]] + "_" + r[ix["performer_id"]]
        n_frames, vt, vf = track_frames[key]
        onset = float(r[ix["onset_sec"]]); offset = float(r[ix["offset_sec"]])
        dur = offset - onset
        t0 = onset + 0.15 * dur; t1 = offset - 0.15 * dur
        sel = (vt >= t0) & (vt <= t1)
        kt, kf = vt[sel], vf[sel]
        # frames (voiced or not) inside trimmed span, from the frame grid k*HOP/SR
        k_lo = int(math.ceil(t0 * SR / HOP - 1e-9))
        k_hi = int(math.floor(t1 * SR / HOP + 1e-9))
        k_lo = max(k_lo, 0); k_hi = min(k_hi, n_frames - 1)
        n_span = max(k_hi - k_lo + 1, 0)
        n_kept = int(len(kf))
        pct = 100.0 * n_kept / n_span if n_span > 0 else 0.0
        if n_kept >= 1:
            sidecar.setdefault(key, {})[int(r[ix["note_idx"]])] = (kt, kf)
        if n_kept >= 5:
            f0m = float(np.median(kf))
            dev = 1200.0 * math.log2(f0m / et_hz(int(r[ix["score_midi"]])))
            new_u[i] = (f"{f0m:.4f}", f"{dev:.2f}", str(n_kept), f"{pct:.1f}", "pyin")
            new_valid[i] = dev
        else:
            new_u[i] = ("", "", str(n_kept), f"{pct:.1f}", "pyin")
            n_short_u_new += 1

    # ---------- 4. flags ----------
    # uniform-side octave flags on NEW devs
    from collections import defaultdict
    by_track = defaultdict(list)
    for i in sorted(new_valid):
        key = rows[i][ix["take_id"]] + "_" + rows[i][ix["performer_id"]]
        by_track[key].append(i)
    fl_u_new = {}
    for key, idxs in by_track.items():
        fl = runmed_octave_flags([new_valid[i] for i in idxs])
        for i, f in zip(idxs, fl):
            fl_u_new[i] = f
    suspect_new = {i: (1 if (fl_b.get(i, 0) or fl_u_new.get(i, 0)) else 0)
                   for i in range(len(rows))}
    short_new = {}
    for i, r in enumerate(rows):
        best_short = (r[ix["f0_median_hz_best"]] == "")
        uni_short = i not in new_valid
        short_new[i] = 1 if (best_short or uni_short) else 0

    # ---------- 5. sidecars ----------
    os.makedirs(SIDE_DIR, exist_ok=True)
    for key, notes in sidecar.items():
        payload = {}
        for nidx, (kt, kf) in notes.items():
            payload[f"n{nidx}_t_u"] = kt
            payload[f"n{nidx}_f_u"] = kf
        np.savez(os.path.join(SIDE_DIR, f"{key}.npz"), **payload)
    print(f"sidecars written: {len(sidecar)} files -> {SIDE_DIR}")

    # ---------- 6. CSV rewrite with byte-identity check ----------
    out_lines = [header]
    n_tail = len(hdr) - 12  # fields 12..27 -> 16 splits
    for i, line in enumerate(data_lines):
        parts = line.rsplit(",", n_tail)
        assert len(parts) == n_tail + 1, f"rsplit failed row {i}"
        # parts[0] = fields 0..11 (incl quoted json); parts[j] = field 11+j
        # sanity: verify untouched fields match csv parse
        f0s, devs, nks, pcts, src = new_u[i]
        parts[3] = f0s          # f0_median_hz_uniform (field 14)
        parts[4] = devs         # dev_cents_uniform (15)
        parts[5] = nks          # n_kept_uniform (16)
        parts[6] = pcts         # voiced_pct_uniform (17)
        parts[7] = src          # label_source_uniform (18)
        parts[14] = str(short_new[i])    # short_note_flag (25)
        parts[15] = str(suspect_new[i])  # suspect_octave_flag (26)
        out_lines.append(",".join(parts))
    # byte-identity verification of untouched fields
    for i, (old, new) in enumerate(zip(data_lines, out_lines[1:])):
        po, pn = old.rsplit(",", n_tail), new.rsplit(",", n_tail)
        for j in (0, 1, 2, 8, 9, 10, 11, 12, 13, 16):
            assert po[j] == pn[j], f"untouched field changed row {i} part {j}"
    tmp = CSV_PATH + ".v2tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines) + "\n")
    os.replace(tmp, CSV_PATH)
    print(f"table rewritten: {CSV_PATH} ({len(out_lines)-1} rows)")

    # ---------- 7. stats + self-check ----------
    # old uniform values from backup already in rows (parsed before rewrite)
    def fnum(s):
        return float(s) if s != "" else None
    mic_of = {k: v["mic"] for k, v in track_map.items()}
    chosen_by = {k: v["chosen_by"] for k, v in track_map.items()}
    stats = defaultdict(list)
    diffs_old, diffs_best = [], []
    per_mic_best = defaultdict(list)
    per_mic_old = defaultdict(list)
    filled_rows = 0
    filled_valid = 0
    for i, r in enumerate(rows):
        key = r[ix["take_id"]] + "_" + r[ix["performer_id"]]
        mic = mic_of[key]
        dev_new = new_valid.get(i)
        dev_old = fnum(r[ix["dev_cents_uniform"]])
        dev_best = fnum(r[ix["dev_cents_best"]])
        if chosen_by[key] == "pref_rule_fill":
            filled_rows += 1
            if dev_new is not None:
                filled_valid += 1
        if dev_new is not None and dev_best is not None:
            per_mic_best[mic].append(abs(dev_new - dev_best))
            diffs_best.append(abs(dev_new - dev_best))
        if dev_new is not None and dev_old is not None:
            per_mic_old[mic].append(abs(dev_new - dev_old))
            diffs_old.append(abs(dev_new - dev_old))
    rep = {}
    rep["n_rows"] = len(rows)
    rep["valid_uniform_new"] = len(new_valid)
    rep["valid_uniform_old"] = sum(1 for r in rows if r[ix["dev_cents_uniform"]] != "")
    rep["short_uniform_new"] = n_short_u_new
    rep["filled_rows_prev_missing"] = filled_rows
    rep["filled_valid_prev_missing"] = filled_valid
    rep["short_flag_new_total"] = sum(short_new.values())
    rep["suspect_flag_new_total"] = sum(suspect_new.values())
    rep["suspect_uniform_side_new"] = sum(fl_u_new.values())
    rep["suspect_best_side"] = sum(fl_b.values())
    rep["suspect_old_total"] = n_flag_old
    rep["short_old_total"] = sn_old
    d = np.array(diffs_old)
    rep["old_vs_new"] = dict(n=len(d), median=float(np.median(d)),
                             tail_gt50=float((d > 50).mean()))
    d = np.array(diffs_best)
    rep["new_vs_best"] = dict(n=len(d), median=float(np.median(d)),
                              tail_gt50=float((d > 50).mean()))
    rep["per_mic_median_new_vs_best"] = {m: (len(v), float(np.median(v)))
                                         for m, v in sorted(per_mic_best.items())}
    rep["per_mic_median_new_vs_old"] = {m: (len(v), float(np.median(v)))
                                        for m, v in sorted(per_mic_old.items())}
    rep["extraction_wall_min"] = round(ext_wall / 60, 1)
    rep["audio_min"] = round(audio_secs / 60, 1)

    # self-check: 5 random notes re-derived from sidecars + dev formula
    rng = np.random.default_rng(SEED)
    new_rows = list(csv.reader(open(CSV_PATH)))[1:]
    valid_idx = [i for i in range(len(new_rows)) if new_rows[i][ix["f0_median_hz_uniform"]] != ""]
    picks = rng.choice(valid_idx, size=5, replace=False)
    checks = []
    for i in picks:
        r = new_rows[i]
        key = r[ix["take_id"]] + "_" + r[ix["performer_id"]]
        nidx = int(r[ix["note_idx"]])
        z = np.load(os.path.join(SIDE_DIR, f"{key}.npz"))
        f0m = float(np.median(z[f"n{nidx}_f_u"]))
        csv_f0 = float(r[ix["f0_median_hz_uniform"]])
        csv_dev = float(r[ix["dev_cents_uniform"]])
        dev_calc = 1200.0 * math.log2(csv_f0 / et_hz(int(r[ix["score_midi"]])))
        ok_f0 = abs(f0m - csv_f0) < 5e-4
        ok_dev = abs(dev_calc - csv_dev) < 0.01
        checks.append(f"{key} n{nidx}: csv={csv_f0:.4f} npz={f0m:.4f} "
                      f"{'OK' if ok_f0 else 'FAIL'} | dev csv={csv_dev:.2f} "
                      f"calc={dev_calc:.2f} {'OK' if ok_dev else 'FAIL'}")
    rep["selfcheck_notes"] = checks
    new_header = open(CSV_PATH).readline().rstrip("\n")
    rep["schema_unchanged"] = (new_header == EXPECTED_HEADER)
    rep["total_wall_min"] = round((time.time() - t_start) / 60, 1)

    print(json.dumps(rep, indent=1))
    with open(os.path.join(ROOT, "code", "dagstuhl_v2_report.json"), "w") as f:
        json.dump(rep, f, indent=1)


if __name__ == "__main__":
    main()
