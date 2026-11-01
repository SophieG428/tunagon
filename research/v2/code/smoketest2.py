"""v2 smoke test: synthetic data WITH injected drift + scale-degree + coupling
signal, so causal_inter should beat causal, and beat the shuffled control."""
import json, os, sys
import numpy as np
import pandas as pd

RUN = os.environ.get("AT_RUN", ".")
rng = np.random.default_rng(11)
PARTS = [("S", "s1", 71), ("A", "a1", 64), ("T", "t1", 59), ("B", "b1", 50)]
DEG_FX = {0: 4, 2: -3, 4: -8, 5: 2, 7: 1, 9: -5, 11: 9}  # scale-degree effect, cents

rows = []
takes = [("p1", "t1"), ("p1", "t2"), ("p2", "t1"), ("p2", "t2"), ("p3", "t1")]
for piece, take in takes:
    icept = float(rng.normal(0, 15))
    slope = float(rng.normal(0, 0.25))
    events = []
    for part, perf, base in PARTS:
        t = float(rng.uniform(0, 0.3))
        for i in range(70):
            dur = float(rng.uniform(0.35, 0.8))
            midi = int(base + rng.choice([0, 2, 4, 5, 7, 9, 11]) - 5 + rng.integers(0, 2))
            events.append(dict(part=part, perf=perf, idx=i, on=round(t, 3),
                               off=round(t + dur, 3), midi=midi))
            t += dur + float(rng.uniform(0.0, 0.15))
    events.sort(key=lambda e: e["on"])
    done = {p: [] for p, _, _ in PARTS}  # per part: (offset, detrended dev), completed
    for e in events:
        # couple on partners' most recent COMPLETED note (what a live engine hears)
        partners = []
        for p, hist in done.items():
            if p == e["part"]:
                continue
            recent = [d for off, d in hist if off <= e["on"] and e["on"] - off <= 5.0]
            if recent:
                partners.append(recent[-1])
        coupling = 0.5 * float(np.mean(partners)) if partners else 0.0
        deg = (e["midi"] - 50) % 12
        base_dev = (icept + slope * e["on"] + DEG_FX.get(deg, 0) + coupling
                    + float(rng.normal(0, 7)))
        e["dev"] = round(base_dev, 2)
        done[e["part"]].append((e["off"], e["dev"] - (icept + slope * e["on"])))
    for e in events:
        conc = [x["midi"] for x in events
                if x["part"] != e["part"] and x["on"] <= (e["on"] + e["off"]) / 2 < x["off"]]
        f0 = 440 * 2 ** ((e["midi"] - 69) / 12) * 2 ** (e["dev"] / 1200)
        rows.append(dict(
            dataset="smoke2", piece_id=piece, take_id=f"{piece}_{take}",
            performer_id=e["perf"], part=e["part"], instrument="voice", note_idx=e["idx"],
            score_midi=e["midi"], onset_sec=e["on"], offset_sec=e["off"],
            duration_sec=round(e["off"] - e["on"], 3),
            concurrent_midi_json=json.dumps(conc), bass_midi=min([e["midi"]] + conc) if conc else e["midi"],
            is_open_string=0,
            f0_median_hz_uniform=round(f0, 3), dev_cents_uniform=e["dev"],
            n_kept_uniform=20, voiced_pct_uniform=90.0, label_source_uniform="pyin",
            f0_median_hz_best=round(f0, 3), dev_cents_best=e["dev"],
            n_kept_best=20, voiced_pct_best=95.0, label_source_best="pyin",
            onset_refined_ms=0, short_note_flag=0, suspect_octave_flag=0, is_control=0))

df = pd.DataFrame(rows)
df.to_csv(f"{RUN}/notes_tables/smoke2.csv", index=False)
print("wrote", len(df), "rows,", df.take_id.nunique(), "takes,", df.piece_id.nunique(), "pieces")
