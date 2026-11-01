"""v2 feature building: full (= v1), causal (real-time-available only), and
leakage-safe partner-interaction features for the coupling analysis.

Causal rule: a feature may use only information available at the moment a note
STARTS on the instrument: the note itself, elapsed time, that part's previous
note, and what is currently sounding (with measurements that FINISHED earlier).
No durations, no next notes, no whole-take statistics.
"""
import json
import numpy as np
import pandas as pd

from features import build_features as build_full_features, ji_offset_cents, JI_OFFSETS, SEED

PART_VOCAB = ["S", "A", "T", "B", "vn1", "vn2", "va", "vc"]
VOCAL_PARTS = {"S", "A", "T", "B"}
# live-available tessitura reference: fixed typical center per part (no take stats)
STATIC_CENTER = {"S": 69, "A": 64, "T": 57, "B": 50,
                 "vn1": 76, "vn2": 76, "va": 65, "vc": 50}

PARTNER_WINDOW_S = 5.0   # a partner's "most recent" note must have ended within this
ENSEMBLE_WINDOW_S = 2.0  # ensemble-mean window before onset


def _take_key(df):
    return df["dataset"].astype(str) + "|" + df["take_id"].astype(str)


def build_causal_features(df, pooled=False):
    """Score-free-of-lookahead features. Returns (X, names)."""
    df = df.copy()
    out = pd.DataFrame(index=df.index)
    out["score_midi"] = df["score_midi"].astype(float)
    out["pitch_class"] = df["score_midi"].astype(int) % 12
    out["octave"] = df["score_midi"].astype(int) // 12
    out["onset_sec"] = df["onset_sec"].astype(float)  # elapsed time: live-available

    take = _take_key(df)
    track = take + "|" + df["part"].astype(str) + "|" + df["performer_id"].astype(str)
    df["_track"] = track
    df = df.sort_values(["_track", "onset_sec", "note_idx"])
    g = df.groupby("_track", sort=False)
    prev_midi = g["score_midi"].shift(1)
    prev_off = g["offset_sec"].shift(1)
    mel = pd.DataFrame(index=df.index)
    mel["prev_interval"] = (df["score_midi"] - prev_midi).fillna(0.0)
    mel["is_first_note"] = prev_midi.isna().astype(float)
    mel["is_repeat"] = (mel["prev_interval"] == 0).astype(float) * (1 - mel["is_first_note"])
    mel["rest_before"] = (df["onset_sec"] - prev_off).clip(lower=0).fillna(0.0)
    out = out.join(mel)

    out["tessitura_static"] = df["score_midi"].astype(float) - df["part"].map(STATIC_CENTER).fillna(60)
    for p in PART_VOCAB:
        out[f"part_{p}"] = (df["part"] == p).astype(float)
    out["is_vocal"] = df["part"].isin(VOCAL_PARTS).astype(float)
    out["is_open_string"] = df["is_open_string"].fillna(0).astype(float)
    out["ensemble_size"] = df.groupby(take.loc[df.index])["part"].transform("nunique").astype(float)

    # chord context from notes SOUNDING AT ONSET (other parts only)
    snd = _sounding_at_onset(df)
    out["n_sounding"] = snd["n_sounding"]
    out["interval_to_bass_snd"] = snd["interval_to_bass"]
    out["is_lowest_snd"] = snd["is_lowest"]
    for name in ["has_m3", "has_M3", "has_P5", "has_tt"]:
        out[name + "_snd"] = snd[name]
    out["unison_snd"] = snd["unison"]
    out["ji_offset_causal"] = snd["ji_offset"]

    if pooled:
        for ds in sorted(df["dataset"].unique()):
            out[f"ds_{ds}"] = (df["dataset"] == ds).astype(float)
        out["is_strings"] = (~df["part"].isin(VOCAL_PARTS)).astype(float)

    out = out.sort_index()
    return out.astype(float), list(out.columns)


def _sounding_at_onset(df):
    """For each note: other-part notes with onset_j <= onset_i < offset_j."""
    res = pd.DataFrame(0.0, index=df.index,
                       columns=["n_sounding", "interval_to_bass", "is_lowest",
                                "has_m3", "has_M3", "has_P5", "has_tt",
                                "unison", "ji_offset"])
    for _, gi in df.groupby(_take_key(df), sort=False):
        on = gi["onset_sec"].to_numpy(float)
        off = gi["offset_sec"].to_numpy(float)
        midi = gi["score_midi"].to_numpy(int)
        part = gi["part"].to_numpy()
        n = len(gi)
        order = np.argsort(on, kind="stable")
        for ii in range(n):
            i = order[ii]
            t = on[i]
            mask = (on <= t) & (off > t) & (part != part[i])
            idx = gi.index[i]
            if not mask.any():
                res.loc[idx, "interval_to_bass"] = 0.0
                res.loc[idx, "is_lowest"] = 1.0
                continue
            sm = midi[mask]
            bass = min(int(sm.min()), int(midi[i]))
            res.loc[idx, "n_sounding"] = float(mask.sum())
            res.loc[idx, "interval_to_bass"] = float((midi[i] - bass) % 12)
            res.loc[idx, "is_lowest"] = float(midi[i] <= sm.min())
            pcs = {(int(m) - bass) % 12 for m in sm} | {(int(midi[i]) - bass) % 12}
            res.loc[idx, "has_m3"] = float(3 in pcs)
            res.loc[idx, "has_M3"] = float(4 in pcs)
            res.loc[idx, "has_P5"] = float(7 in pcs)
            res.loc[idx, "has_tt"] = float(6 in pcs)
            res.loc[idx, "unison"] = float(int(midi[i]) in set(int(m) for m in sm))
            res.loc[idx, "ji_offset"] = JI_OFFSETS[int(midi[i] - bass) % 12]
    return res


def build_interaction_features(df, y, donor_map=None):
    """Leakage-safe partner features. y: frame-transformed label per row (same
    index as df). donor_map: {take_key: donor_take_key} for the shuffled-partner
    control — partner history is then read from the DONOR take of the same piece
    (timelines of takes of the same piece are comparable). Returns (X, names).

    Per target note at onset t, using only partner notes whose measurement
    FINISHED (offset <= t):
      partner_last_mean : mean over other parts of that part's most recent
                          completed deviation (within PARTNER_WINDOW_S)
      partner_mean_2s   : mean deviation of other-part notes ending in [t-2, t)
      partner_bass_last : most recent completed deviation of the lowest-pitched
                          among each part's most recent notes
      n_partner_parts   : how many other parts contributed
    """
    cols = ["partner_last_mean", "partner_mean_2s", "partner_bass_last", "n_partner_parts"]
    res = pd.DataFrame(0.0, index=df.index, columns=cols)
    tk = _take_key(df)
    groups = {k: g for k, g in df.groupby(tk, sort=False)}
    yv = y.astype(float)

    for key, gi in groups.items():
        src_key = donor_map.get(key) if donor_map else key
        gs = groups.get(src_key)
        if gs is None or len(gs) == 0:
            continue
        s_off = gs["offset_sec"].to_numpy(float)
        s_part = gs["part"].to_numpy()
        s_midi = gs["score_midi"].to_numpy(int)
        s_y = yv.loc[gs.index].to_numpy(float)
        s_valid = np.isfinite(s_y)
        order = np.argsort(s_off, kind="stable")
        s_off, s_part, s_midi, s_y, s_valid = (a[order] for a in (s_off, s_part, s_midi, s_y, s_valid))

        for idx, t, my_part in zip(gi.index, gi["onset_sec"].to_numpy(float), gi["part"].to_numpy()):
            hi = np.searchsorted(s_off, t, side="right")  # completed before onset
            if hi == 0:
                continue
            lastdev, lastmidi = {}, {}
            for j in range(hi - 1, -1, -1):
                if t - s_off[j] > PARTNER_WINDOW_S:
                    break  # offsets sorted ascending: everything older is further out
                p = s_part[j]
                if p == my_part or p in lastdev or not s_valid[j]:
                    continue
                lastdev[p] = s_y[j]
                lastmidi[p] = s_midi[j]
            if lastdev:
                vals = np.array(list(lastdev.values()))
                res.loc[idx, "partner_last_mean"] = float(vals.mean())
                res.loc[idx, "n_partner_parts"] = float(len(vals))
                bass_p = min(lastmidi, key=lastmidi.get)
                res.loc[idx, "partner_bass_last"] = float(lastdev[bass_p])
            lo = np.searchsorted(s_off, t - ENSEMBLE_WINDOW_S, side="left")
            win = slice(lo, hi)
            wmask = (s_part[win] != my_part) & s_valid[win]
            if wmask.any():
                res.loc[idx, "partner_mean_2s"] = float(s_y[win][wmask].mean())
    return res.astype(float), cols


def make_donor_map(df, rng_seed=SEED):
    """Round-robin donor take of the SAME piece for the shuffled-partner control.
    Takes with no same-piece sibling get no donor (excluded from shuffle runs)."""
    donor = {}
    meta = df[["dataset", "piece_id", "take_id"]].drop_duplicates()
    meta["key"] = meta["dataset"].astype(str) + "|" + meta["take_id"].astype(str)
    for (_, _), g in meta.groupby(["dataset", "piece_id"]):
        keys = sorted(g["key"])
        if len(keys) < 2:
            continue
        for i, k in enumerate(keys):
            donor[k] = keys[(i + 1) % len(keys)]
    return donor
