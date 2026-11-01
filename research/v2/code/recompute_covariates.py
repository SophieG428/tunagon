"""Central covariate recomputation (verification MUST-FIX #2).

One exact Theil-Sen implementation for every dataset, replacing the agents'
three variants. Covariates are analysis deliverables; training computes its
own frames internally and is unaffected.
"""
import os
import numpy as np
import pandas as pd

RUN = os.environ.get("AT_RUN", "/private/tmp/at-run")


def exact_theil_sen(t, y):
    n = len(y)
    if n < 5:
        return (float(np.median(y)) if n else np.nan), 0.0
    iu = np.triu_indices(n, 1)
    dt = (t[:, None] - t[None, :])[iu]
    dy = (y[:, None] - y[None, :])[iu]
    m = np.abs(dt) > 1e-6
    if not m.any():
        return float(np.median(y)), 0.0
    slope = float(np.median(dy[m] / dt[m]))
    return float(np.median(y - slope * t)), slope


for ds in ["dagstuhl", "esmuc", "csd"]:
    df = pd.read_csv(f"{RUN}/notes_tables/{ds}.csv")
    val = df[(df.short_note_flag.fillna(0) == 0) & (df.suspect_octave_flag.fillna(0) == 0)]
    rows = []
    for (p, take), g in val.groupby(["piece_id", "take_id"]):
        row = dict(dataset=ds, piece_id=p, take_id=take)
        for pipe in ["uniform", "best"]:
            gg = g[g[f"dev_cents_{pipe}"].notna()]
            t = gg.onset_sec.to_numpy(float)
            y = gg[f"dev_cents_{pipe}"].to_numpy(float)
            ic, sl = exact_theil_sen(t, y)
            fc = (float(gg.loc[gg.onset_sec <= gg.onset_sec.min() + 3.0,
                               f"dev_cents_{pipe}"].median()) if len(gg) else np.nan)
            osr = gg.loc[gg.is_open_string == 1, f"dev_cents_{pipe}"]
            row.update({
                f"intercept_cents_{pipe}": round(ic, 3) if ic == ic else "",
                f"slope_cents_per_sec_{pipe}": round(sl, 4),
                f"first_chord_offset_cents_{pipe}": round(fc, 3) if fc == fc else "",
                f"open_string_offset_cents_{pipe}": round(float(osr.median()), 3) if len(osr) else "",
                f"n_notes_used_{pipe}": int(len(gg))})
        rows.append(row)
    pd.DataFrame(rows).to_csv(f"{RUN}/covariates/{ds}.csv", index=False)
    print(ds, len(rows), "takes recomputed")
