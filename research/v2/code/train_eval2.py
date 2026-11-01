"""v2 training/evaluation: Tunagon-phase protocol (AT_RESEARCH_NEXT_STEPS.md).

Adds to v1:
  - third frame 'det' (per-take intercept AND slope removed)      [Step 1]
  - causal feature set (real-time-available information only)     [Step 2]
  - leakage-safe partner-interaction features + shuffled-partner
    control + lagged drift cross-correlation                      [Step 4]
  - per-model wall-time instrumentation; optional model saving

Run matrix per dataset (per available label pipeline):
  full   x {raw, rel, det}
  causal x {raw, rel, det}
  causal_inter (causal + real partner features)    x {rel, det}
  causal_shuf  (causal + shuffled-partner control) x {rel, det}
Pooled (non-control datasets): det x {full, causal, causal_inter}.
Transfer runs: dropped in v2 (answered by v1).

Resume-safe: per-fold checkpoints in results_v2/metrics_partial.csv.
Usage: python train_eval2.py [--datasets ...] [--save-models]
"""
import argparse, json, os, sys, time, warnings
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.inspection import permutation_importance

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from features import build_features as build_full, ji_offset_cents, SEED
from features2 import build_causal_features, build_interaction_features, make_donor_map

RUN = os.environ.get("AT_RUN", ".")
NOTES_DIR = f"{RUN}/notes_tables"
RESULTS = f"{RUN}/results_v2"
PARTIAL = f"{RESULTS}/metrics_partial.csv"
IMP_PATH = f"{RESULTS}/importances.csv"
CONTROL_DATASETS = {"csd"}
PIPELINES = ["best", "uniform"]
FRAMES_BY_FS = {"full": ["raw", "rel", "det"], "causal": ["raw", "rel", "det"],
                "causal_inter": ["rel", "det"], "causal_shuf": ["rel", "det"]}
HGB_GRID = [dict(max_depth=d, max_leaf_nodes=l, l2_regularization=r)
            for d in [3, None] for l in [15, 31] for r in [0.0, 10.0]]
RIDGE_ALPHAS = [0.1, 1.0, 10.0, 100.0, 1000.0]
rng = np.random.default_rng(SEED)


def append_csv(path, records):
    if records:
        pd.DataFrame(records).to_csv(path, mode="a", header=not os.path.exists(path), index=False)


def load_done():
    if not os.path.exists(PARTIAL):
        return [], set()
    prev = pd.read_csv(PARTIAL)
    keys = set(zip(prev["run"].astype(str), prev["fold"].astype(str), prev["model"].astype(str)))
    return prev.to_dict("records"), keys


def valid_rows(df, pipeline):
    col = f"dev_cents_{pipeline}"
    m = (df[col].notna() & (df["short_note_flag"].fillna(0) == 0)
         & (df["suspect_octave_flag"].fillna(0) == 0))
    return df.loc[m].copy()


def theil_sen(t, y, max_pairs=20000):
    n = len(y)
    if n < 5:
        return (float(np.median(y)) if n else 0.0), 0.0
    idx = rng.choice(n, size=(min(max_pairs, n * (n - 1) // 2), 2))
    idx = idx[idx[:, 0] != idx[:, 1]]
    dt = t[idx[:, 0]] - t[idx[:, 1]]
    keep = np.abs(dt) > 1e-6
    slopes = (y[idx[:, 0]] - y[idx[:, 1]])[keep] / dt[keep]
    slope = float(np.median(slopes)) if len(slopes) else 0.0
    return float(np.median(y - slope * t)), slope


def prep(df, pipeline, frame):
    """Valid rows + frame-transformed label in _y."""
    d = valid_rows(df, pipeline)
    if len(d) < 200:
        return None
    col = f"dev_cents_{pipeline}"
    d["_take"] = d["dataset"] + "|" + d["take_id"].astype(str)
    d["_piece"] = d["dataset"] + "|" + d["piece_id"].astype(str)
    d["_y"] = d[col].astype(float)
    if frame != "raw":
        for take, g in d.groupby("_take"):
            icept, slope = theil_sen(g["onset_sec"].to_numpy(float), g["_y"].to_numpy(float))
            if frame == "rel":
                d.loc[g.index, "_y"] = g["_y"] - icept
            else:  # det
                d.loc[g.index, "_y"] = g["_y"] - (icept + slope * g["onset_sec"])
    return d.loc[d["_y"].notna()].reset_index(drop=True)


def build_X(d, fs, pooled):
    if fs == "full":
        X, names = build_full(d, pooled=pooled)
        return X.to_numpy(float), names
    X, names = build_causal_features(d, pooled=pooled)
    if fs in ("causal_inter", "causal_shuf"):
        donor = make_donor_map(d) if fs == "causal_shuf" else None
        XI, ni = build_interaction_features(d, d["_y"], donor_map=donor)
        X = pd.concat([X, XI], axis=1)
        names = names + ni
    return X.to_numpy(float), names


def inner_folds(train_df):
    pieces = train_df["_piece"].unique()
    if len(pieces) >= 2:
        return [((train_df["_piece"] != p).to_numpy(), (train_df["_piece"] == p).to_numpy()) for p in pieces]
    takes = train_df["_take"].unique()
    if len(takes) >= 2:
        return [((train_df["_take"] != t).to_numpy(), (train_df["_take"] == t).to_numpy()) for t in takes]
    parts = rng.permutation(len(train_df)) % 3
    return [((parts != k), (parts == k)) for k in range(3)]


def _make(model_name, cand):
    if model_name == "hgb_tuned":
        return HistGradientBoostingRegressor(learning_rate=0.05, max_iter=400,
                                             early_stopping=False, random_state=SEED, **cand)
    return make_pipeline(StandardScaler(), Ridge(alpha=cand, random_state=SEED))


def fit_predict(model_name, Xtr, ytr, Xte, train_df):
    t0 = time.perf_counter()
    if model_name == "hgb_default":
        m = HistGradientBoostingRegressor(random_state=SEED)
        m.fit(Xtr, ytr)
        return m.predict(Xte), m, None, time.perf_counter() - t0
    folds = inner_folds(train_df)
    cands = HGB_GRID if model_name == "hgb_tuned" else RIDGE_ALPHAS
    scores = []
    for cand in cands:
        errs = []
        for tr_m, va_m in folds:
            if tr_m.sum() < 20 or va_m.sum() < 5:
                continue
            m = _make(model_name, cand)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                m.fit(Xtr[tr_m], ytr[tr_m])
            errs.append(np.mean(np.abs(m.predict(Xtr[va_m]) - ytr[va_m])))
        scores.append(np.mean(errs) if errs else np.inf)
    best = cands[int(np.argmin(scores))]
    m = _make(model_name, best)
    m.fit(Xtr, ytr)
    return m.predict(Xte), m, best, time.perf_counter() - t0


def baseline_predict(name, test_df, train_df):
    if name == "zero":
        return np.zeros(len(test_df))
    if name == "part_mean":
        means = train_df.groupby("part")["_y"].mean()
        return test_df["part"].map(means).fillna(train_df["_y"].mean()).to_numpy(float)
    if name == "ji_rule":
        return test_df.apply(ji_offset_cents, axis=1).to_numpy(float)
    raise ValueError(name)


def metrics(y, yhat):
    err = yhat - y
    out = dict(mae=float(np.mean(np.abs(err))), rmse=float(np.sqrt(np.mean(err ** 2))), n=int(len(y)))
    out["pearson_r"] = (float(np.corrcoef(y, yhat)[0, 1])
                        if len(y) > 2 and np.std(y) > 1e-9 and np.std(yhat) > 1e-9 else np.nan)
    return out


def run_cv(d, tag, fs, pooled, rows, done, do_importance, save_models):
    X_all, feat_names = build_X(d, fs, pooled)
    y_all = d["_y"].to_numpy(float)
    for piece in sorted(d["_piece"].unique()):
        if (tag, str(piece), "hgb_tuned") in done:
            continue
        te = (d["_piece"] == piece).to_numpy()
        tr = ~te
        if te.sum() < 10 or tr.sum() < 50:
            continue
        train_df = d.loc[tr]
        fold_rows, imp_rows, fold_preds = [], [], {}
        for model in ["hgb_tuned", "hgb_default", "ridge"]:
            yhat, fitted, chosen, secs = fit_predict(model, X_all[tr], y_all[tr], X_all[te], train_df)
            fold_preds[model] = yhat
            row = dict(run=tag, fold=piece, model=model, fit_seconds=round(secs, 2),
                       chosen=json.dumps(chosen, default=str), **metrics(y_all[te], yhat))
            if model == "hgb_tuned":
                if do_importance:
                    t0 = time.perf_counter()
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        pi = permutation_importance(fitted, X_all[te], y_all[te], n_repeats=5,
                                                    random_state=SEED,
                                                    scoring="neg_mean_absolute_error")
                    imp_rows = [dict(run=tag, fold=piece, feature=f, importance=v)
                                for f, v in zip(feat_names, pi.importances_mean)]
                    row["importance_seconds"] = round(time.perf_counter() - t0, 2)
                if save_models:
                    import joblib
                    os.makedirs(f"{RESULTS}/models", exist_ok=True)
                    safe = f"{tag}__{piece}".replace("|", "_").replace("/", "_")
                    joblib.dump(fitted, f"{RESULTS}/models/{safe}.joblib")
            fold_rows.append(row)
        for b in ["zero", "part_mean", "ji_rule"]:
            yhat = baseline_predict(b, d.loc[te], train_df)
            fold_preds[b] = yhat
            fold_rows.append(dict(run=tag, fold=piece, model=b, fit_seconds=0.0, chosen="",
                                  **metrics(y_all[te], yhat)))
        te_df = d.loc[te]
        for part, gp in te_df.groupby("part"):
            sel = te_df.index.get_indexer(gp.index)
            fold_rows.append(dict(run=tag, fold=f"{piece}|part={part}", model="hgb_tuned",
                                  fit_seconds=0.0, chosen="",
                                  **metrics(y_all[te][sel], fold_preds["hgb_tuned"][sel])))
        os.makedirs(f"{RESULTS}/predictions", exist_ok=True)
        out = te_df[["dataset", "piece_id", "take_id", "part", "note_idx", "onset_sec", "_y"]].copy()
        for k, v in fold_preds.items():
            out[f"pred_{k}"] = v
        safe = str(piece).replace("/", "_").replace("|", "_")
        out.to_csv(f"{RESULTS}/predictions/{tag.replace('|','_')}__{safe}.csv", index=False)
        rows.extend(fold_rows)
        append_csv(PARTIAL, fold_rows)
        append_csv(IMP_PATH, imp_rows)
        print(f"[fold done] {tag} :: {piece}", flush=True)


def drift_xcorr(data):
    """Step 4.3b: lagged cross-correlation between parts' drift curves per take."""
    recs = []
    for name, df in data.items():
        d = valid_rows(df, "best")
        d["_take"] = d["dataset"] + "|" + d["take_id"].astype(str)
        for take, g in d.groupby("_take"):
            t1 = g["offset_sec"].max()
            grid = np.arange(0, t1, 1.0)
            curves = {}
            for part, gp in g.groupby("part"):
                if len(gp) < 20:
                    continue
                on = gp["onset_sec"].to_numpy(float)
                dv = gp["dev_cents_best"].to_numpy(float)
                c = np.array([np.median(dv[(on >= x - 2) & (on <= x + 2)])
                              if ((on >= x - 2) & (on <= x + 2)).sum() >= 3 else np.nan
                              for x in grid])
                if np.isfinite(c).sum() >= 20:
                    curves[part] = c
            parts = sorted(curves)
            for i in range(len(parts)):
                for j in range(len(parts)):
                    if i == j:
                        continue
                    a, b = curves[parts[i]], curves[parts[j]]
                    best_lag, best_r, r0 = 0, np.nan, np.nan
                    for lag in range(-5, 6):
                        if lag < 0:
                            x, y = a[-lag:], b[:len(b) + lag]
                        elif lag > 0:
                            x, y = a[:len(a) - lag], b[lag:]
                        else:
                            x, y = a, b
                        m = np.isfinite(x) & np.isfinite(y)
                        if m.sum() < 15 or np.std(x[m]) < 1e-9 or np.std(y[m]) < 1e-9:
                            continue
                        r = float(np.corrcoef(x[m], y[m])[0, 1])
                        if lag == 0:
                            r0 = r
                        if not np.isfinite(best_r) or r > best_r:
                            best_lag, best_r = lag, r
                    recs.append(dict(dataset=name, take=take, part_a=parts[i], part_b=parts[j],
                                     best_lag_s=best_lag, r_at_best=best_r, r_at_0=r0))
    pd.DataFrame(recs).to_csv(f"{RESULTS}/xcorr.csv", index=False)
    print(f"[xcorr] {len(recs)} pair-take rows", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", nargs="+",
                    default=[f[:-4] for f in sorted(os.listdir(NOTES_DIR)) if f.endswith(".csv")
                             and not f.endswith("_backup.csv")])
    ap.add_argument("--save-models", action="store_true")
    args = ap.parse_args()
    os.makedirs(RESULTS, exist_ok=True)
    data = {n: pd.read_csv(f"{NOTES_DIR}/{n}.csv") for n in args.datasets}
    for df in data.values():
        df["dataset"] = df["dataset"].astype(str)
    rows, done = load_done()
    if done:
        print(f"[resume] {len(done)} checkpointed entries", flush=True)

    if not os.path.exists(f"{RESULTS}/xcorr.csv"):
        drift_xcorr(data)

    for name, df in data.items():
        ident = df["dev_cents_best"].equals(df["dev_cents_uniform"])
        for pipeline in PIPELINES:
            if pipeline == "uniform" and ident:
                print(f"[skip] {name} uniform == best", flush=True)
                continue
            for fs, frames in FRAMES_BY_FS.items():
                for frame in frames:
                    d = prep(df, pipeline, frame)
                    if d is None:
                        continue
                    if fs == "causal_shuf":
                        donor = make_donor_map(d)
                        d = d[(d["dataset"] + "|" + d["take_id"].astype(str)).isin(donor)].reset_index(drop=True)
                        if len(d) < 200:
                            print(f"[skip] v2|{name}|{pipeline}|{frame}|{fs} — no shufflable takes", flush=True)
                            continue
                    tag = f"v2|{name}|{pipeline}|{frame}|{fs}"
                    do_imp = (pipeline == "best" and frame == "det"
                              and fs in ("full", "causal", "causal_inter"))
                    print(f"[run] {tag} n={len(d)}", flush=True)
                    run_cv(d, tag, fs, pooled=False, rows=rows, done=done,
                           do_importance=do_imp, save_models=args.save_models)

    main_sets = [n for n in data if n not in CONTROL_DATASETS]
    if len(main_sets) >= 2:
        for fs in ["full", "causal", "causal_inter"]:
            parts = [prep(data[n], "best", "det") for n in main_sets]
            parts = [p for p in parts if p is not None]
            if len(parts) < 2:
                continue
            d = pd.concat(parts, ignore_index=True)
            tag = f"v2|pooled[{'+'.join(main_sets)}]|best|det|{fs}"
            print(f"[run] {tag} n={len(d)}", flush=True)
            run_cv(d, tag, fs, pooled=True, rows=rows, done=done,
                   do_importance=True, save_models=args.save_models)

    final = pd.DataFrame(rows).drop_duplicates(subset=["run", "fold", "model"], keep="last")
    final.to_csv(f"{RESULTS}/raw_metrics.csv", index=False)
    print(f"[done] wrote raw_metrics.csv ({len(final)} rows)", flush=True)


if __name__ == "__main__":
    main()
