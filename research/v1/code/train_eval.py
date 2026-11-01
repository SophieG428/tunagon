"""Central training/evaluation per CONTRACT.md.

Runs, per dataset and label pipeline (best / uniform), in both frames
(raw A440 / ensemble-relative):
  - nested leave-one-piece-out CV (inner tuning inside training folds only)
  - models: HGB tuned, HGB defaults, ridge tuned
  - baselines: predict-zero (ET), per-part train mean, just-intonation rule
Plus pooled (non-control datasets) and pairwise transfer runs.

Resume-safe: every completed outer fold is checkpointed to
results/metrics_partial.csv (and importances.csv); rerunning skips finished
work. Root dir comes from $AT_RUN (default /private/tmp/at-run).

Usage: python train_eval.py [--datasets dagstuhl esmuc csd]
"""
import argparse, itertools, json, os, sys, warnings
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.inspection import permutation_importance

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from features import build_features, ji_offset_cents, SEED

RUN = os.environ.get("AT_RUN", "/private/tmp/at-run")
NOTES_DIR = f"{RUN}/notes_tables"
RESULTS = f"{RUN}/results"
PARTIAL = f"{RESULTS}/metrics_partial.csv"
IMP_PATH = f"{RESULTS}/importances.csv"
CONTROL_DATASETS = {"csd"}
PIPELINES = ["best", "uniform"]
HGB_GRID = [dict(max_depth=d, max_leaf_nodes=l, l2_regularization=r)
            for d in [3, None] for l in [15, 31] for r in [0.0, 10.0]]
RIDGE_ALPHAS = [0.1, 1.0, 10.0, 100.0, 1000.0]
rng = np.random.default_rng(SEED)


def append_csv(path, records):
    if not records:
        return
    df = pd.DataFrame(records)
    df.to_csv(path, mode="a", header=not os.path.exists(path), index=False)


def load_done():
    """(run, fold, model) keys already checkpointed."""
    if not os.path.exists(PARTIAL):
        return [], set()
    prev = pd.read_csv(PARTIAL)
    keys = set(zip(prev["run"].astype(str), prev["fold"].astype(str),
                   prev["model"].astype(str)))
    return prev.to_dict("records"), keys


def load_dataset(name):
    df = pd.read_csv(f"{NOTES_DIR}/{name}.csv")
    df["dataset"] = df["dataset"].astype(str)
    return df


def valid_rows(df, pipeline):
    col = f"dev_cents_{pipeline}"
    m = (df[col].notna() & (df["short_note_flag"].fillna(0) == 0)
         & (df["suspect_octave_flag"].fillna(0) == 0))
    return df.loc[m].copy()


def theil_sen(t, y, max_pairs=20000):
    """Robust intercept/slope of y vs t (median of pairwise slopes)."""
    n = len(y)
    if n < 5:
        return float(np.median(y)) if n else 0.0, 0.0
    idx = rng.choice(n, size=(min(max_pairs, n * (n - 1) // 2), 2))
    idx = idx[idx[:, 0] != idx[:, 1]]
    dt = t[idx[:, 0]] - t[idx[:, 1]]
    keep = np.abs(dt) > 1e-6
    slopes = (y[idx[:, 0]] - y[idx[:, 1]])[keep] / dt[keep]
    slope = float(np.median(slopes)) if len(slopes) else 0.0
    return float(np.median(y - slope * t)), slope


def add_frames(df, pipeline):
    """Adds y_raw and y_rel (raw minus per-take Theil-Sen intercept)."""
    col = f"dev_cents_{pipeline}"
    df = df.copy()
    df["y_raw"] = df[col].astype(float)
    df["y_rel"] = np.nan
    df["_take"] = df["dataset"] + "|" + df["take_id"].astype(str)
    for take, g in df.groupby("_take"):
        icept, _ = theil_sen(g["onset_sec"].to_numpy(float), g["y_raw"].to_numpy(float))
        df.loc[g.index, "y_rel"] = g["y_raw"] - icept
    return df


def inner_folds(train_df):
    """Contract rule: LOPO over training pieces if >=2 pieces, else group by take."""
    pieces = train_df["_piece"].unique()
    if len(pieces) >= 2:
        return [(train_df["_piece"] != p, train_df["_piece"] == p) for p in pieces]
    takes = train_df["_take"].unique()
    if len(takes) >= 2:
        return [(train_df["_take"] != t, train_df["_take"] == t) for t in takes]
    parts = rng.permutation(len(train_df)) % 3
    return [(pd.Series(parts != k, index=train_df.index),
             pd.Series(parts == k, index=train_df.index)) for k in range(3)]


def fit_predict(model_name, Xtr, ytr, Xte, train_df, feat_names):
    """Nested tuning inside the training set only; returns predictions on Xte."""
    if model_name == "hgb_default":
        m = HistGradientBoostingRegressor(random_state=SEED)
        m.fit(Xtr, ytr)
        return m.predict(Xte), m, None
    if model_name in ("hgb_tuned", "ridge"):
        folds = inner_folds(train_df)
        cands = (HGB_GRID if model_name == "hgb_tuned" else RIDGE_ALPHAS)
        scores = []
        for cand in cands:
            errs = []
            for tr_m, va_m in folds:
                tr_m = np.asarray(tr_m); va_m = np.asarray(va_m)
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
        return m.predict(Xte), m, best
    raise ValueError(model_name)


def _make(model_name, cand):
    if model_name == "hgb_tuned":
        return HistGradientBoostingRegressor(learning_rate=0.05, max_iter=400,
                                             early_stopping=False, random_state=SEED, **cand)
    return make_pipeline(StandardScaler(), Ridge(alpha=cand, random_state=SEED))


def baseline_predict(name, test_df, train_df):
    if name == "zero":
        return np.zeros(len(test_df))
    if name == "part_mean":
        means = train_df.groupby("part")["_y"].mean()
        overall = train_df["_y"].mean()
        return test_df["part"].map(means).fillna(overall).to_numpy(float)
    if name == "ji_rule":
        return test_df.apply(ji_offset_cents, axis=1).to_numpy(float)
    raise ValueError(name)


def metrics(y, yhat):
    err = yhat - y
    out = dict(mae=float(np.mean(np.abs(err))), rmse=float(np.sqrt(np.mean(err ** 2))),
               n=int(len(y)))
    out["pearson_r"] = (float(np.corrcoef(y, yhat)[0, 1])
                        if len(y) > 2 and np.std(y) > 1e-9 and np.std(yhat) > 1e-9 else np.nan)
    return out


def run_cv(df, tag, pooled, rows, done, preds_dir):
    """Leave-one-piece-out over df (label in _y). Checkpoints per fold."""
    X_all, feat_names = build_features(df, pooled=pooled)
    X_all = X_all.to_numpy(float)
    y_all = df["_y"].to_numpy(float)
    for piece in sorted(df["_piece"].unique()):
        if (tag, str(piece), "hgb_tuned") in done:
            continue
        te = (df["_piece"] == piece).to_numpy()
        tr = ~te
        if te.sum() < 10 or tr.sum() < 50:
            continue
        train_df = df.loc[tr]
        fold_rows, imp_rows, fold_preds = [], [], {}
        for model in ["hgb_tuned", "hgb_default", "ridge"]:
            yhat, fitted, chosen = fit_predict(model, X_all[tr], y_all[tr], X_all[te],
                                               train_df, feat_names)
            fold_preds[model] = yhat
            fold_rows.append(dict(run=tag, fold=piece, model=model,
                                  chosen=json.dumps(chosen, default=str),
                                  **metrics(y_all[te], yhat)))
            if model == "hgb_tuned" and "|best|" in tag:
                # interpretation runs only; uniform runs are label-robustness
                # checks and skip the (expensive) permutation importance
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    pi = permutation_importance(fitted, X_all[te], y_all[te], n_repeats=5,
                                                random_state=SEED,
                                                scoring="neg_mean_absolute_error")
                imp_rows = [dict(run=tag, fold=piece, feature=f, importance=v)
                            for f, v in zip(feat_names, pi.importances_mean)]
        for b in ["zero", "part_mean", "ji_rule"]:
            yhat = baseline_predict(b, df.loc[te], train_df)
            fold_preds[b] = yhat
            fold_rows.append(dict(run=tag, fold=piece, model=b, chosen="",
                                  **metrics(y_all[te], yhat)))
        te_df = df.loc[te]
        for part, gp in te_df.groupby("part"):
            sel = te_df.index.get_indexer(gp.index)
            fold_rows.append(dict(run=tag, fold=f"{piece}|part={part}", model="hgb_tuned",
                                  chosen="", **metrics(y_all[te][sel],
                                                       fold_preds["hgb_tuned"][sel])))
        os.makedirs(preds_dir, exist_ok=True)
        safe = str(piece).replace("/", "_").replace("|", "_")
        out = te_df[["dataset", "piece_id", "take_id", "part", "note_idx",
                     "onset_sec", "_y"]].copy()
        for k, v in fold_preds.items():
            out[f"pred_{k}"] = v
        out.to_csv(f"{preds_dir}/{tag.replace('|','_')}__{safe}.csv", index=False)
        rows.extend(fold_rows)
        append_csv(PARTIAL, fold_rows)   # checkpoint: fold is durable from here
        append_csv(IMP_PATH, imp_rows)
        print(f"[fold done] {tag} :: {piece}", flush=True)


def prep(df, pipeline, frame):
    d = valid_rows(df, pipeline)
    if len(d) < 200:
        return None
    d = add_frames(d, pipeline)
    d["_piece"] = d["dataset"] + "|" + d["piece_id"].astype(str)
    d["_y"] = d["y_raw"] if frame == "raw" else d["y_rel"]
    return d.loc[d["_y"].notna()].reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", nargs="+",
                    default=[f[:-4] for f in sorted(os.listdir(NOTES_DIR)) if f.endswith(".csv")])
    args = ap.parse_args()
    os.makedirs(RESULTS, exist_ok=True)
    data = {name: load_dataset(name) for name in args.datasets}
    rows, done = load_done()
    if done:
        print(f"[resume] {len(done)} checkpointed (run,fold,model) entries found", flush=True)

    for name, df in data.items():
        # single-F0-source datasets have byte-identical pipelines: computing the
        # 'uniform' runs would duplicate the 'best' numbers exactly — skip them
        ident = df["dev_cents_best"].equals(df["dev_cents_uniform"])
        for pipeline in PIPELINES:
            if pipeline == "uniform" and ident:
                print(f"[skip] per|{name}|uniform* — labels identical to 'best'", flush=True)
                continue
            for frame in ["raw", "rel"]:
                d = prep(df, pipeline, frame)
                if d is None:
                    continue
                tag = f"per|{name}|{pipeline}|{frame}"
                print(f"[run] {tag} n={len(d)}", flush=True)
                run_cv(d, tag, pooled=False, rows=rows, done=done,
                       preds_dir=f"{RESULTS}/predictions")

    main_sets = [n for n in data if n not in CONTROL_DATASETS]
    if len(main_sets) >= 2:
        for pipeline in PIPELINES:
            for frame in ["raw", "rel"]:
                parts = [prep(data[n], pipeline, frame) for n in main_sets]
                parts = [p for p in parts if p is not None]
                if len(parts) < 2:
                    continue
                d = pd.concat(parts, ignore_index=True)
                tag = f"pooled|{'+'.join(main_sets)}|{pipeline}|{frame}"
                print(f"[run] {tag} n={len(d)}", flush=True)
                run_cv(d, tag, pooled=True, rows=rows, done=done,
                       preds_dir=f"{RESULTS}/predictions")
        for pipeline in PIPELINES:
            for frame in ["raw", "rel"]:
                cache = {n: prep(data[n], pipeline, frame) for n in main_sets}
                for a, b in itertools.permutations(main_sets, 2):
                    tag = f"transfer|{a}->{b}|{pipeline}|{frame}"
                    if (tag, "all", "hgb_tuned") in done:
                        continue
                    da, db = cache[a], cache[b]
                    if da is None or db is None:
                        continue
                    both = pd.concat([da, db], ignore_index=True)
                    X, feat_names = build_features(both, pooled=False)
                    X = X.to_numpy(float)
                    na = len(da)
                    yhat, fitted, chosen = fit_predict("hgb_tuned", X[:na],
                                                       both["_y"].to_numpy(float)[:na],
                                                       X[na:], da, feat_names)
                    t_rows = [dict(run=tag, fold="all", model="hgb_tuned",
                                   chosen=json.dumps(chosen, default=str),
                                   **metrics(db["_y"].to_numpy(float), yhat))]
                    for base in ["zero", "ji_rule"]:
                        t_rows.append(dict(run=tag, fold="all", model=base, chosen="",
                                           **metrics(db["_y"].to_numpy(float),
                                                     baseline_predict(base, db, da))))
                    rows.extend(t_rows)
                    append_csv(PARTIAL, t_rows)
                    print(f"[fold done] {tag} :: all", flush=True)

    final = pd.DataFrame(rows).drop_duplicates(subset=["run", "fold", "model"], keep="last")
    final.to_csv(f"{RESULTS}/raw_metrics.csv", index=False)
    print(f"[done] wrote raw_metrics.csv ({len(final)} rows)", flush=True)


if __name__ == "__main__":
    main()
