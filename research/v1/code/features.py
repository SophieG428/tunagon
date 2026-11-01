"""Central feature building per CONTRACT.md. Score-only features from note tables.

Agents never touch this: identical features for every dataset, built from the
standardized note-table schema. The just-intonation rule lives here too (it is
both a baseline predictor and an input feature).
"""
import json
import numpy as np
import pandas as pd

SEED = 20260813

PART_VOCAB = ["S", "A", "T", "B", "vn1", "vn2", "va", "vc"]
VOCAL_PARTS = {"S", "A", "T", "B"}

# 5-limit just-intonation offsets in cents vs equal temperament, indexed by
# interval class (semitones mod 12) above the chord root (root approximated as
# the lowest concurrent score note; the root itself stays at ET).
# Ratios: 16/15, 9/8, 6/5, 5/4, 4/3, 45/32, 3/2, 8/5, 5/3, 9/5, 15/8.
# Values reviewed against LIT_BRIEF.md before results are reported.
JI_OFFSETS = {0: 0.0, 1: 11.7, 2: 3.9, 3: 15.6, 4: -13.7, 5: -2.0,
              6: -9.8, 7: 2.0, 8: 13.7, 9: -15.6, 10: 17.6, 11: -11.7}


def _parse_concurrent(s):
    if isinstance(s, str) and s.strip():
        try:
            return [int(x) for x in json.loads(s)]
        except (ValueError, json.JSONDecodeError):
            return []
    return []


def ji_offset_cents(row):
    """Just-intonation rule prediction for one note (cents vs ET)."""
    bass = row["bass_midi"]
    if not np.isfinite(bass):
        return 0.0
    ic = int(row["score_midi"] - bass) % 12
    return JI_OFFSETS[ic]


def build_features(df, pooled=False):
    """df: standardized note table (one or more datasets). Returns (X, feat_names).

    All features are derivable from score + alignment timing; none use audio.
    """
    df = df.copy()
    df["concurrent_list"] = df["concurrent_midi_json"].map(_parse_concurrent)

    out = pd.DataFrame(index=df.index)
    out["score_midi"] = df["score_midi"].astype(float)
    out["pitch_class"] = df["score_midi"].astype(int) % 12
    out["octave"] = df["score_midi"].astype(int) // 12
    out["duration_sec"] = df["duration_sec"].astype(float)
    out["log_duration"] = np.log1p(df["duration_sec"].astype(float))
    out["onset_sec"] = df["onset_sec"].astype(float)

    # position within the take (0..1)
    take_key = df["dataset"] + "|" + df["take_id"].astype(str)
    take_end = df.groupby(take_key)["offset_sec"].transform("max")
    out["position_norm"] = (df["onset_sec"] / take_end.clip(lower=1e-9)).clip(0, 1)

    # melodic context within a track (same take, part, performer), by onset order
    track_key = take_key + "|" + df["part"].astype(str) + "|" + df["performer_id"].astype(str)
    df["_track"] = track_key
    df = df.sort_values(["_track", "onset_sec", "note_idx"])
    g = df.groupby("_track", sort=False)
    prev_midi = g["score_midi"].shift(1)
    next_midi = g["score_midi"].shift(-1)
    prev_off = g["offset_sec"].shift(1)
    order = df.index  # remember sorted order, map back at the end
    mel = pd.DataFrame(index=df.index)
    mel["prev_interval"] = (df["score_midi"] - prev_midi).fillna(0.0)
    mel["next_interval"] = (next_midi - df["score_midi"]).fillna(0.0)
    mel["is_first_note"] = prev_midi.isna().astype(float)
    mel["is_repeat"] = (mel["prev_interval"] == 0).astype(float) * (1 - mel["is_first_note"])
    mel["rest_before"] = (df["onset_sec"] - prev_off).clip(lower=0).fillna(0.0)
    out = out.join(mel.loc[order])

    # tessitura: pitch relative to this part's median in this take
    part_take = take_key + "|" + df["part"].astype(str)
    part_med = df.groupby(part_take)["score_midi"].transform("median")
    out.loc[df.index, "tessitura"] = (df["score_midi"] - part_med).astype(float)

    # part / instrument identity
    for p in PART_VOCAB:
        out[f"part_{p}"] = (df["part"] == p).astype(float)
    out["is_vocal"] = df["part"].isin(VOCAL_PARTS).astype(float)

    # vertical (score harmony) context
    conc = df["concurrent_list"]
    out["n_concurrent"] = conc.map(len).astype(float)
    out["ensemble_size"] = df.groupby(take_key)["part"].transform("nunique").astype(float)
    bass = df["bass_midi"].astype(float)
    out["interval_to_bass"] = ((df["score_midi"] - bass) % 12).astype(float)
    out["is_bass"] = (df["score_midi"] <= bass).astype(float)
    out["compound_above_bass"] = ((df["score_midi"] - bass) // 12).clip(lower=0).astype(float)

    def chord_flags(row):
        pcs = {(int(m) - int(row["bass_midi"])) % 12 for m in row["concurrent_list"]}
        pcs.add((int(row["score_midi"]) - int(row["bass_midi"])) % 12)
        return pcs
    pcs_col = df.apply(chord_flags, axis=1)
    for name, ic in [("has_m3", 3), ("has_M3", 4), ("has_P5", 7),
                     ("has_m7", 10), ("has_M7", 11), ("has_tt", 6)]:
        out[name] = pcs_col.map(lambda s, ic=ic: float(ic in s))
    out["unison_with_other"] = df.apply(
        lambda r: float(int(r["score_midi"]) in r["concurrent_list"]), axis=1)

    out["is_open_string"] = df["is_open_string"].fillna(0).astype(float)

    # the JI rule value doubles as an input feature (rule-informed feature)
    out["ji_offset"] = df.apply(ji_offset_cents, axis=1)

    if pooled:
        for ds in sorted(df["dataset"].unique()):
            out[f"ds_{ds}"] = (df["dataset"] == ds).astype(float)
        out["is_strings"] = (~df["part"].isin(VOCAL_PARTS)).astype(float)

    out = out.sort_index()
    return out.astype(float), list(out.columns)
