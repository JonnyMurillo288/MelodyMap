"""
Evaluate already-trained embeddings against the link model.
Uses the two embedding files we already have:
  /tmp/exp_embeddings_expB_baseline_p1q1.csv
  /tmp/exp_embeddings_expB_p1_q0.5.csv

Run from: /home/jonnym/Desktop/MelodyMap/internal/interlude_service/machinelearning/
    python experiments/eval_existing_embeddings.py
"""
import os, sys, time, json, warnings, gc
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = "/home/jonnym/Desktop/MelodyMap/internal/interlude_service/machinelearning"
sys.path.insert(0, PROJECT_ROOT)

from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    roc_auc_score, average_precision_score, precision_score,
    recall_score, f1_score, accuracy_score,
)

import sklearn.utils
if not hasattr(sklearn.utils, "indices_to_mask"):
    sklearn.utils.indices_to_mask = lambda idx, l: np.array([i in set(idx) for i in range(l)])
import sklearn.utils.metaestimators
if not hasattr(sklearn.utils.metaestimators, "if_delegate_has_method"):
    sklearn.utils.metaestimators.if_delegate_has_method = lambda d: (lambda fn: fn)

from pulearn import ElkanotoPuClassifier
from utils.metrics import l2_normalize
from features.build_features import build_feature_row, compute_popularity_interactions

V6_FEATURES = [
    "cos_sim_src_dst", "l2_dist_src_dst", "popularity_dst", "popularity_src",
    "num_dst_neighbors", "max_cos_srcnbr_dst", "mean_topk_cos_dstnbr_src",
    "preferential_attachment", "adamic_adar", "jaccard_neighbors",
    "popularity_ratio", "popularity_diff", "popularity_product", "log_popularity_ratio",
]

V6_BASELINE = {
    "balanced_recall": 0.9283, "precision": 0.9684,
    "link_recall": 0.9613, "nolink_recall": 0.8953, "roc_auc": 0.9839,
}


def load_pop_map():
    df = pd.read_csv("/tmp/exp_popularity_map.csv")
    return dict(zip(df["artist_id"].astype(str), df["popularity_score"]))


def load_pairs(seed=42):
    return pd.read_csv(f"/tmp/exp_training_pairs_100000_0.3_{seed}.csv")


def build_neighbors(edges_df):
    neighbors = {}
    for s, d in zip(edges_df["src"].astype(str), edges_df["dst"].astype(str)):
        neighbors.setdefault(s, set()).add(d)
        neighbors.setdefault(d, set()).add(s)
    return {k: list(v) for k, v in neighbors.items()}


def build_lookup(emb_df, pop_map):
    EMB_COLS = [c for c in emb_df.columns if c.startswith("emb_")]
    emb_vals = emb_df[EMB_COLS].values.astype(np.float32)
    norms = np.linalg.norm(emb_vals, axis=1, keepdims=True)
    emb_vals = emb_vals / (norms + 1e-12)
    aids = emb_df["artist_id"].astype(str).values
    return {aids[i]: {"emb": emb_vals[i].astype(np.float64), "popularity": pop_map.get(aids[i], 0.0)} for i in range(len(aids))}


def build_features(lookup, neighbors, pairs_df):
    rows = []
    skip = 0
    total = len(pairs_df)
    for idx, r in pairs_df.iterrows():
        s, d = str(r["src"]), str(r["dst"])
        if s not in lookup or d not in lookup:
            skip += 1
            continue
        feats = build_feature_row(s, d, lookup, neighbors, topk=3)
        feats["src"] = s
        feats["dst"] = d
        feats["label"] = r["label"]
        rows.append(feats)
        if (idx + 1) % 20000 == 0:
            print(f"  Built {idx+1}/{total} features...")

    print(f"  Done: {len(rows)} rows, {skip} skipped")
    df = pd.DataFrame(rows)
    if "popularity_src" in df.columns:
        compute_popularity_interactions(df)
    return df


def train_eval(feat_df, seed=42):
    avail = [f for f in V6_FEATURES if f in feat_df.columns]
    X = feat_df[avail].values
    y = feat_df["label"].values
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=seed, stratify=y)

    logit = LogisticRegression(penalty="elasticnet", solver="saga", max_iter=3000,
                               C=1.0, l1_ratio=0.3, random_state=seed)
    pu = ElkanotoPuClassifier(estimator=logit, hold_out_ratio=0.2)
    pipe = Pipeline([("imp", SimpleImputer(strategy="median")),
                     ("scl", StandardScaler()), ("pu", pu)])
    t0 = time.time()
    pipe.fit(Xtr, ytr)
    tt = time.time() - t0

    yp = pipe.predict_proba(Xte)
    if yp.ndim > 1 and yp.shape[1] > 1:
        yp = yp[:, 1]
    yp = np.clip(yp, 0, 0.994)

    sweep = []
    for thr in np.arange(0.20, 0.71, 0.05):
        pred = (yp >= thr).astype(int)
        lm = yte == 1; nm = yte == 0
        lr = (pred[lm] == 1).sum() / lm.sum() if lm.sum() else 0
        nr = (pred[nm] == 0).sum() / nm.sum() if nm.sum() else 0
        sweep.append({"thr": round(float(thr), 2),
                      "prec": float(precision_score(yte, pred, zero_division=0)),
                      "lr": float(lr), "nr": float(nr), "br": float((lr + nr) / 2),
                      "f1": float(f1_score(yte, pred, zero_division=0))})

    roc = float(roc_auc_score(yte, yp))
    pr = float(average_precision_score(yte, yp))
    best = max(sweep, key=lambda x: x["br"])

    return {"roc_auc": roc, "pr_auc": pr, "train_s": tt,
            "thr": best["thr"], "prec": best["prec"],
            "lr": best["lr"], "nr": best["nr"], "br": best["br"],
            "f1": best["f1"], "sweep": sweep}, pipe


def show(label, m):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  ROC={m['roc_auc']:.4f} Prec={m['prec']:.4f} LR={m['lr']:.4f} "
          f"NLR={m['nr']:.4f} BR={m['br']:.4f} F1={m['f1']:.4f} thr={m['thr']:.2f}")
    d = m['br'] - V6_BASELINE['balanced_recall']
    print(f"  Delta BR vs v6: {d:+.4f}")
    print(f"  {'Thr':>5} {'Prec':>6} {'LR':>6} {'NLR':>6} {'BR':>6} {'F1':>6}")
    for s in m["sweep"]:
        mk = " *" if s["thr"] == m["thr"] else ""
        print(f"  {s['thr']:5.2f} {s['prec']:6.4f} {s['lr']:6.4f} {s['nr']:6.4f} {s['br']:6.4f} {s['f1']:6.4f}{mk}")


def main():
    print("Loading edges...")
    edges_df = pd.read_csv("/tmp/exp_artist_edges.csv")
    print(f"  {len(edges_df)} edges")

    print("Building neighbors dict...")
    neighbors = build_neighbors(edges_df)
    print(f"  {len(neighbors)} artists in graph")

    print("Loading popularity map...")
    pop_map = load_pop_map()

    print("Loading pairs (seed=42)...")
    pairs = load_pairs(42)
    print(f"  {len(pairs)} pairs: {pairs['label'].value_counts().to_dict()}")

    # Evaluate each embedding
    configs = [
        ("p=1.0, q=1.0 (baseline)", "/tmp/exp_embeddings_expB_baseline_p1q1.csv"),
        ("p=1.0, q=0.5 (DFS-biased)", "/tmp/exp_embeddings_expB_p1_q0.5.csv"),
    ]

    results = {}
    for name, path in configs:
        print(f"\n{'#'*60}")
        print(f"# Evaluating: {name}")
        print(f"# File: {path}")
        print(f"{'#'*60}")

        if not os.path.exists(path):
            print(f"  SKIP: file not found")
            continue

        print("  Loading embeddings...")
        emb_df = pd.read_csv(path)
        print(f"  {len(emb_df)} artists, {len([c for c in emb_df.columns if c.startswith('emb_')])} dims")

        print("  Building lookup...")
        lookup = build_lookup(emb_df, pop_map)
        del emb_df
        gc.collect()

        print("  Building features...")
        feat_df = build_features(lookup, neighbors, pairs)
        del lookup
        gc.collect()

        print("  Training model...")
        metrics, pipe = train_eval(feat_df, seed=42)
        del feat_df
        gc.collect()

        results[name] = metrics
        show(name, metrics)

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    for name, m in results.items():
        d_br = m['br'] - V6_BASELINE['balanced_recall']
        d_prec = m['prec'] - V6_BASELINE['precision']
        print(f"  {name}: BR={m['br']:.4f} ({d_br:+.4f}) Prec={m['prec']:.4f} ({d_prec:+.4f})")

    # Save
    report_path = os.path.join(PROJECT_ROOT, "experiments", "results", "eval_existing_embeddings.json")
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {report_path}")


if __name__ == "__main__":
    main()
