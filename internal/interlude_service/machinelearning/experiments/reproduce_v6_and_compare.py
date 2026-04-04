"""
1. Reproduce v6 baseline using v6 training data.
2. For each new embedding, recompute embedding-dependent features.
3. Compare across embeddings.

Run from: /home/jonnym/Desktop/MelodyMap/internal/interlude_service/machinelearning/
    python experiments/reproduce_v6_and_compare.py
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
    recall_score, f1_score,
)

import sklearn.utils
if not hasattr(sklearn.utils, "indices_to_mask"):
    sklearn.utils.indices_to_mask = lambda idx, l: np.array([i in set(idx) for i in range(l)])
import sklearn.utils.metaestimators
if not hasattr(sklearn.utils.metaestimators, "if_delegate_has_method"):
    sklearn.utils.metaestimators.if_delegate_has_method = lambda d: (lambda fn: fn)

from pulearn import ElkanotoPuClassifier
from utils.metrics import l2_normalize

RESULTS_DIR = os.path.join(PROJECT_ROOT, "experiments", "results")

V6_FEATURES = [
    "cos_sim_src_dst", "l2_dist_src_dst", "popularity_dst", "popularity_src",
    "num_dst_neighbors", "max_cos_srcnbr_dst", "mean_topk_cos_dstnbr_src",
    "preferential_attachment", "adamic_adar", "jaccard_neighbors",
    "popularity_ratio", "popularity_diff", "popularity_product", "log_popularity_ratio",
]

# Embedding-dependent features (change when we swap embeddings)
EMB_DEPENDENT = [
    "cos_sim_src_dst", "l2_dist_src_dst",
    "max_cos_srcnbr_dst", "mean_topk_cos_dstnbr_src",
]

V6_BASELINE_REF = {
    "balanced_recall": 0.9283, "precision": 0.9684,
    "link_recall": 0.9613, "nolink_recall": 0.8953, "roc_auc": 0.9839,
}

TRAINING_DATA = os.path.join(PROJECT_ROOT, "training_data", "artist_embeddings_collab_neg.csv")


def train_eval(df, features, seed=42):
    # Compute popularity interactions if needed
    if "popularity_ratio" not in df.columns and "popularity_src" in df.columns:
        pop_src = df["popularity_src"]; pop_dst = df["popularity_dst"]
        pop_max = np.maximum(pop_src, pop_dst); pop_min = np.minimum(pop_src, pop_dst)
        df["popularity_ratio"] = pop_max / (pop_min + 1e-8)
        df["popularity_diff"] = np.abs(pop_src - pop_dst)
        df["popularity_product"] = pop_src * pop_dst
        df["log_popularity_ratio"] = np.log1p(df["popularity_ratio"])

    avail = [f for f in features if f in df.columns]
    missing = set(features) - set(avail)
    if missing:
        print(f"  WARNING: Missing features: {missing}")

    X = df[avail].values
    y = df["label"].values

    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=seed, stratify=y)
    print(f"  Train: {len(ytr)} ({ytr.mean():.3f} pos), Test: {len(yte)} ({yte.mean():.3f} pos)")

    logit = LogisticRegression(penalty="elasticnet", solver="saga", max_iter=3000,
                               C=1.0, l1_ratio=0.3, random_state=seed)
    pu = ElkanotoPuClassifier(estimator=logit, hold_out_ratio=0.2)
    pipe = Pipeline([("imp", SimpleImputer(strategy="median")),
                     ("scl", StandardScaler()), ("pu", pu)])
    t0 = time.time()
    pipe.fit(Xtr, ytr)
    tt = time.time() - t0

    yp = pipe.predict_proba(Xte)
    if yp.ndim > 1 and yp.shape[1] > 1: yp = yp[:, 1]
    yp = np.clip(yp, 0, 0.994)

    sweep = []
    for thr in np.arange(0.20, 0.71, 0.05):
        pred = (yp >= thr).astype(int)
        lm = yte == 1; nm = yte == 0
        lr = float((pred[lm] == 1).sum() / lm.sum()) if lm.sum() else 0
        nr = float((pred[nm] == 0).sum() / nm.sum()) if nm.sum() else 0
        sweep.append({"thr": round(float(thr), 2),
                      "prec": float(precision_score(yte, pred, zero_division=0)),
                      "lr": lr, "nr": nr, "br": (lr + nr) / 2,
                      "f1": float(f1_score(yte, pred, zero_division=0))})

    roc = float(roc_auc_score(yte, yp))
    pr = float(average_precision_score(yte, yp))
    best = max(sweep, key=lambda x: x["br"])

    return {"roc_auc": roc, "pr_auc": pr, "train_s": tt,
            "thr": best["thr"], "prec": best["prec"],
            "lr": best["lr"], "nr": best["nr"], "br": best["br"],
            "f1": best["f1"], "sweep": sweep}, pipe


def show(label, m, ref=V6_BASELINE_REF):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  ROC={m['roc_auc']:.4f} Prec={m['prec']:.4f} LR={m['lr']:.4f} "
          f"NLR={m['nr']:.4f} BR={m['br']:.4f} F1={m['f1']:.4f} thr={m['thr']}")
    d = m['br'] - ref['balanced_recall']
    print(f"  Delta BR vs v6 ref: {d:+.4f}")
    print(f"  {'Thr':>5} {'Prec':>6} {'LR':>6} {'NLR':>6} {'BR':>6} {'F1':>6}")
    for s in m["sweep"]:
        mk = " *" if s["thr"] == m["thr"] else ""
        print(f"  {s['thr']:5.2f} {s['prec']:6.4f} {s['lr']:6.4f} {s['nr']:6.4f} {s['br']:6.4f} {s['f1']:6.4f}{mk}")


def recompute_emb_features(df, emb_df, edges_df):
    """
    Replace embedding-dependent features in df using new embeddings.
    Only changes: cos_sim_src_dst, l2_dist_src_dst, max_cos_srcnbr_dst, mean_topk_cos_dstnbr_src
    """
    EMB_COLS = [c for c in emb_df.columns if c.startswith("emb_")]
    emb_vals = emb_df[EMB_COLS].values.astype(np.float32)
    norms = np.linalg.norm(emb_vals, axis=1, keepdims=True)
    emb_vals = emb_vals / (norms + 1e-12)
    aids = emb_df["artist_id"].astype(str).values
    emb_lookup = {aids[i]: emb_vals[i] for i in range(len(aids))}

    # Build neighbors dict
    neighbors = {}
    for _, row in edges_df.iterrows():
        s, d = str(row["src"]), str(row["dst"])
        neighbors.setdefault(s, set()).add(d)
        neighbors.setdefault(d, set()).add(s)

    new_cos = np.zeros(len(df))
    new_l2 = np.zeros(len(df))
    new_max_srcnbr = np.zeros(len(df))
    new_mean_topk_dstnbr = np.zeros(len(df))

    skip = 0
    for i, r in df.iterrows():
        src = str(r["src"])
        dst = str(r["dst"])

        if src not in emb_lookup or dst not in emb_lookup:
            skip += 1
            continue

        se = emb_lookup[src].astype(np.float64)
        de = emb_lookup[dst].astype(np.float64)

        new_cos[i] = float(se @ de)
        new_l2[i] = float(np.linalg.norm(se - de))

        # max_cos_srcnbr_dst
        src_nbrs = [n for n in neighbors.get(src, set()) if n in emb_lookup]
        if src_nbrs:
            nbr_embs = np.vstack([emb_lookup[n].astype(np.float64) for n in src_nbrs])
            cos_vals = nbr_embs @ de
            new_max_srcnbr[i] = float(cos_vals.max())
        else:
            new_max_srcnbr[i] = 0.0

        # mean_topk_cos_dstnbr_src
        dst_nbrs = [n for n in neighbors.get(dst, set()) if n in emb_lookup]
        if dst_nbrs:
            nbr_embs = np.vstack([emb_lookup[n].astype(np.float64) for n in dst_nbrs])
            cos_vals = nbr_embs @ se
            topk = np.sort(cos_vals)[-min(3, len(cos_vals)):]
            new_mean_topk_dstnbr[i] = float(topk.mean())
        else:
            new_mean_topk_dstnbr[i] = 0.0

        if (i + 1) % 200000 == 0:
            print(f"    Recomputed {i+1}/{len(df)} rows...")

    print(f"  Recomputed {len(df)} rows, {skip} skipped")

    df_new = df.copy()
    df_new["cos_sim_src_dst"] = new_cos
    df_new["l2_dist_src_dst"] = new_l2
    df_new["max_cos_srcnbr_dst"] = new_max_srcnbr
    df_new["mean_topk_cos_dstnbr_src"] = new_mean_topk_dstnbr

    return df_new


def main():
    # === PART 1: Reproduce v6 baseline ===
    print("="*60)
    print("PART 1: Reproduce v6 baseline")
    print("="*60)

    print(f"Loading v6 training data from {TRAINING_DATA}...")
    df = pd.read_csv(TRAINING_DATA, low_memory=False)
    print(f"  Shape: {df.shape}")
    print(f"  Labels: {df['label'].value_counts().to_dict()}")

    # Compute popularity interactions
    if "popularity_ratio" not in df.columns:
        pop_src = df["popularity_src"]; pop_dst = df["popularity_dst"]
        pop_max = np.maximum(pop_src, pop_dst); pop_min = np.minimum(pop_src, pop_dst)
        df["popularity_ratio"] = pop_max / (pop_min + 1e-8)
        df["popularity_diff"] = np.abs(pop_src - pop_dst)
        df["popularity_product"] = pop_src * pop_dst
        df["log_popularity_ratio"] = np.log1p(df["popularity_ratio"])

    print("  Available features:", [c for c in V6_FEATURES if c in df.columns])

    print("\nTraining v6 baseline model (seed=42)...")
    v6_metrics, v6_pipe = train_eval(df, V6_FEATURES, seed=42)
    show("V6 BASELINE REPRODUCTION", v6_metrics)

    # === PART 2: Evaluate with new embeddings ===
    print(f"\n{'='*60}")
    print("PART 2: Evaluate with new embeddings")
    print("="*60)

    # Load edge list for neighbor computation
    print("Loading edges...")
    edges_df = pd.read_csv("/tmp/exp_artist_edges.csv")
    print(f"  {len(edges_df)} edges")

    # Embedding configs to evaluate
    emb_configs = [
        ("p=1.0, q=1.0 (20 walks)", "/tmp/exp_embeddings_expB_baseline_p1q1.csv"),
        ("p=1.0, q=0.5 (20 walks)", "/tmp/exp_embeddings_expB_p1_q0.5.csv"),
    ]

    results = {"v6_baseline": v6_metrics}

    for name, path in emb_configs:
        if not os.path.exists(path):
            print(f"  SKIP: {path} not found")
            continue

        print(f"\n{'#'*60}")
        print(f"# {name}")
        print(f"# {path}")
        print(f"{'#'*60}")

        print("  Loading embeddings...")
        emb_df = pd.read_csv(path)
        print(f"  {len(emb_df)} artists, {len([c for c in emb_df.columns if c.startswith('emb_')])} dims")

        print("  Recomputing embedding-dependent features...")
        df_new = recompute_emb_features(df, emb_df, edges_df)
        del emb_df
        gc.collect()

        print("  Training model...")
        metrics, pipe = train_eval(df_new, V6_FEATURES, seed=42)
        show(name, metrics, ref=v6_metrics)
        results[name] = metrics

        del df_new
        gc.collect()

    # === SUMMARY ===
    print(f"\n{'='*60}")
    print("SUMMARY: All configs vs v6 baseline reproduction")
    print("="*60)
    base_br = results["v6_baseline"]["br"]
    for name, m in results.items():
        d_br = m["br"] - base_br
        d_prec = m["prec"] - results["v6_baseline"]["prec"]
        print(f"  {name:40s}: BR={m['br']:.4f} ({d_br:+.4f}) "
              f"Prec={m['prec']:.4f} ({d_prec:+.4f}) thr={m['thr']}")

    # Save
    report_path = os.path.join(RESULTS_DIR, "v6_reproduce_and_compare.json")
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {report_path}")


if __name__ == "__main__":
    main()
