#!/usr/bin/env python3
"""
Final v7 recalibration: C=0.001, l1=0.3 (selected from sweep).

This configuration was the best from the sweep for probability spread:
  - 118/351 test pairs above 0.5 (was 2/351 with old model)
  - Mean prob = 0.39 (was ~0.00)
  - Balanced recall = 0.9968 (was 0.9995)
  - Precision = 0.9981 (was 0.9997)

Run from: /home/jonnym/Desktop/MelodyMap/internal/interlude_service/machinelearning/
    python3 experiments/exp_v7_recalibrate_final.py
"""
import os
import sys
import time
import json
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = "/home/jonnym/Desktop/MelodyMap/internal/interlude_service/machinelearning"
sys.path.insert(0, PROJECT_ROOT)

import joblib
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    roc_auc_score, precision_score, recall_score, f1_score,
)

import sklearn.utils
if not hasattr(sklearn.utils, "indices_to_mask"):
    def _itm(indices, mask_length):
        m = np.zeros(mask_length, dtype=bool)
        m[indices] = True
        return m
    sklearn.utils.indices_to_mask = _itm
import sklearn.utils.metaestimators
if not hasattr(sklearn.utils.metaestimators, "if_delegate_has_method"):
    sklearn.utils.metaestimators.if_delegate_has_method = lambda d: (lambda fn: fn)

from pulearn import ElkanotoPuClassifier

from utils.database import get_pg_conn
from features.build_features import build_feature_row, compute_popularity_interactions
from features.sampling import get_training_test
from config.config import (
    NODE2VEC_DIM, NODE2VEC_P, NODE2VEC_Q,
    NODE2VEC_EPOCHS, NODE2VEC_WALK_LENGTH,
    NODE2VEC_NUM_WALKS, NODE2VEC_WINDOW_SIZE,
    NODE2VEC_WORKERS,
)

V7_FEATURES = [
    "cos_sim_src_dst", "l2_dist_src_dst", "popularity_dst", "popularity_src",
    "num_dst_neighbors", "max_cos_srcnbr_dst", "mean_topk_cos_dstnbr_src",
    "preferential_attachment", "adamic_adar", "jaccard_neighbors",
    "popularity_ratio", "popularity_diff", "popularity_product", "log_popularity_ratio",
]

PERSISTENT_DIR = os.path.join(PROJECT_ROOT, "training_data", "v7_embeddings")
EDGES_CSV_PATH = os.path.join(PERSISTENT_DIR, "artist_edges.csv")
EMBEDDINGS_CSV_PATH = os.path.join(PERSISTENT_DIR, "artist_embeddings_v7.csv")

MODEL_PATH = os.path.join(PROJECT_ROOT, "feature_engineering", "logit_model_v7.joblib")
META_PATH = os.path.join(PROJECT_ROOT, "feature_engineering", "metadata", "logit_model_v7.json")

TEST_ARTISTS = {
    "Drake": 600808, "Kendrick Lamar": 762201, "Taylor Swift": 399541,
    "Beyonce": 422058, "Radiohead": 66, "The Beatles": 303,
    "Billie Eilish": 1361541, "Bad Bunny": 1492430, "Metallica": 93,
    "Daft Punk": 501, "Adele": 497084, "Frank Ocean": 796562,
    "Arctic Monkeys": 255826, "J. Cole": 650607, "SZA": 997433,
    "Anderson .Paak": 1130852, "Tame Impala": 571280, "Travis Scott": 894303,
    "The Weeknd": 796889, "Ariana Grande": 823336, "Bruno Mars": 641206,
    "Dua Lipa": 1290968, "Childish Gambino": 680671, "Ed Sheeran": 706819,
    "Gorillaz": 22532, "Post Malone": 1258907, "Rihanna": 262731,
}

# Selected config from sweep
CHOSEN_C = 0.001
CHOSEN_L1 = 0.3


def build_neighbors(edges_df):
    neighbors = {}
    for s, d in zip(edges_df["src"].astype(str), edges_df["dst"].astype(str)):
        neighbors.setdefault(s, set()).add(d)
        neighbors.setdefault(d, set()).add(s)
    return {k: list(v) for k, v in neighbors.items()}


def build_lookup(emb_df, pop_map):
    emb_cols = [c for c in emb_df.columns if c.startswith("emb_")]
    emb_vals = emb_df[emb_cols].values.astype(np.float64)
    norms = np.linalg.norm(emb_vals, axis=1, keepdims=True)
    emb_vals = emb_vals / (norms + 1e-12)
    aids = emb_df["artist_id"].astype(str).values
    return {aids[i]: {"emb": emb_vals[i], "popularity": pop_map.get(aids[i], 0.0)}
            for i in range(len(aids))}


def get_pop_map():
    conn = get_pg_conn()
    df = pd.read_sql_query(
        "SELECT a.id AS artist_id, COALESCE(lfm.popularity_score,0) AS popularity_score "
        "FROM artist a LEFT JOIN lastfm_artist_stats lfm ON lfm.artist_mbid::text=a.gid::text",
        conn
    )
    conn.close()
    return dict(zip(df["artist_id"].astype(str), df["popularity_score"]))


def build_features_for_pairs(emb_df, edges_df, pairs_df, pop_map):
    lookup = build_lookup(emb_df, pop_map)
    neighbors = build_neighbors(edges_df)
    rows = []
    skip = 0
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
        if (idx + 1) % 25000 == 0:
            print(f"  Built {idx + 1}/{len(pairs_df)} features...")
    print(f"  Done: {len(rows)} rows, {skip} skipped")
    df = pd.DataFrame(rows)
    if "popularity_src" in df.columns:
        compute_popularity_interactions(df)
    return df


def threshold_sweep(y_true, y_prob):
    results = []
    for thr in np.arange(0.05, 0.80, 0.05):
        pred = (y_prob >= thr).astype(int)
        lm = y_true == 1
        nm = y_true == 0
        lr = (pred[lm] == 1).sum() / lm.sum() if lm.sum() else 0
        nr = (pred[nm] == 0).sum() / nm.sum() if nm.sum() else 0
        results.append({
            "thr": round(float(thr), 2),
            "prec": float(precision_score(y_true, pred, zero_division=0)),
            "recall": float(recall_score(y_true, pred, zero_division=0)),
            "f1": float(f1_score(y_true, pred, zero_division=0)),
            "link_recall": float(lr),
            "nolink_recall": float(nr),
            "balanced_recall": float((lr + nr) / 2),
        })
    return results


def find_threshold_for_target_recall(sweep_results, target_lr=0.90):
    candidates = [r for r in sweep_results if r["link_recall"] >= target_lr]
    if not candidates:
        return min(sweep_results, key=lambda r: r["thr"])
    return max(candidates, key=lambda r: r["thr"])


def build_27_artist_test_features(emb_df, edges_df, pop_map):
    lookup = build_lookup(emb_df, pop_map)
    neighbors = build_neighbors(edges_df)
    ids = list(TEST_ARTISTS.values())
    id_to_name = {v: k for k, v in TEST_ARTISTS.items()}
    pairs = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            pairs.append((ids[i], ids[j]))
    rows = []
    skip = 0
    for s, d in pairs:
        ss, dd = str(s), str(d)
        if ss not in lookup or dd not in lookup:
            skip += 1
            continue
        feats = build_feature_row(ss, dd, lookup, neighbors, topk=3)
        feats["src"] = s
        feats["dst"] = d
        feats["src_name"] = id_to_name[s]
        feats["dst_name"] = id_to_name[d]
        rows.append(feats)
    print(f"  27-artist test: {len(rows)} pairs built, {skip} skipped")
    df = pd.DataFrame(rows)
    if "popularity_src" in df.columns:
        compute_popularity_interactions(df)
    return df


def main():
    print("=" * 70)
    print(f"  V7 FINAL RECALIBRATION: C={CHOSEN_C}, l1={CHOSEN_L1}")
    print("=" * 70)

    t_total = time.time()

    # Load data
    print("\n[1] Loading embeddings + edges...")
    emb_df = pd.read_csv(EMBEDDINGS_CSV_PATH)
    edges_df = pd.read_csv(EDGES_CSV_PATH)

    print("\n[2] Getting training pairs...")
    conn = get_pg_conn()
    pairs = get_training_test(conn, 100000, 0.30, 42, 5, 5)
    conn.close()
    print(f"  Pairs: {len(pairs)}, labels: {pairs['label'].value_counts().to_dict()}")

    print("\n[3] Getting popularity map...")
    pop_map = get_pop_map()

    print("\n[4] Building features...")
    feat_df = build_features_for_pairs(emb_df, edges_df, pairs, pop_map)
    avail = [f for f in V7_FEATURES if f in feat_df.columns]

    print("\n[5] Building 27-artist test features...")
    test_df = build_27_artist_test_features(emb_df, edges_df, pop_map)

    # 3-seed training
    X_all = feat_df[avail].values
    y_all = feat_df["label"].values

    print(f"\n[6] 3-seed training with C={CHOSEN_C}, l1={CHOSEN_L1}...")
    seed_results = []
    best_pipe = None
    best_br = -1

    for seed in [42, 123, 456]:
        Xtr, Xte, ytr, yte = train_test_split(
            X_all, y_all, test_size=0.2, random_state=seed, stratify=y_all
        )

        logit = LogisticRegression(
            penalty="elasticnet", solver="saga", max_iter=5000,
            C=CHOSEN_C, l1_ratio=CHOSEN_L1, random_state=seed,
        )
        pu = ElkanotoPuClassifier(estimator=logit, hold_out_ratio=0.2)
        pipe = Pipeline([
            ("imp", SimpleImputer(strategy="median")),
            ("scl", StandardScaler()),
            ("pu", pu),
        ])

        t0 = time.time()
        pipe.fit(Xtr, ytr)
        train_time = time.time() - t0

        yp = pipe.predict_proba(Xte)
        if yp.ndim > 1 and yp.shape[1] > 1:
            yp = yp[:, 1]
        yp = np.clip(yp, 0, 0.994)

        sweep = threshold_sweep(yte, yp)
        chosen = find_threshold_for_target_recall(sweep, 0.90)
        roc = float(roc_auc_score(yte, yp))

        result = {
            "seed": seed, "roc_auc": roc, "train_s": train_time,
            "thr": chosen["thr"], "prec": chosen["prec"],
            "link_recall": chosen["link_recall"], "nolink_recall": chosen["nolink_recall"],
            "balanced_recall": chosen["balanced_recall"], "f1": chosen["f1"],
        }
        seed_results.append(result)

        print(f"  Seed {seed}: ROC={roc:.4f} Prec={chosen['prec']:.4f} "
              f"LR={chosen['link_recall']:.4f} NR={chosen['nolink_recall']:.4f} "
              f"BR={chosen['balanced_recall']:.4f} thr={chosen['thr']}")

        if chosen["balanced_recall"] > best_br:
            best_br = chosen["balanced_recall"]
            best_pipe = pipe

    # Mean metrics
    mean = {k: np.mean([s[k] for s in seed_results])
            for k in ["roc_auc", "prec", "link_recall", "nolink_recall", "balanced_recall"]}
    mean_thr = np.mean([s["thr"] for s in seed_results])
    final_threshold = round(mean_thr * 20) / 20

    print(f"\n  3-seed mean: ROC={mean['roc_auc']:.4f} Prec={mean['prec']:.4f} "
          f"LR={mean['link_recall']:.4f} NR={mean['nolink_recall']:.4f} BR={mean['balanced_recall']:.4f} thr={final_threshold}")

    # 27-artist test
    print(f"\n[7] 27-artist test ({len(test_df)} pairs)...")
    X_test_27 = test_df[avail].values
    yp_27 = best_pipe.predict_proba(X_test_27)
    if yp_27.ndim > 1 and yp_27.shape[1] > 1:
        yp_27 = yp_27[:, 1]
    yp_27 = np.clip(yp_27, 0, 0.994)

    print(f"  Prob distribution:")
    for lo, hi, label in [(0, 0.01, "<0.01"), (0.01, 0.1, "0.01-0.10"),
                           (0.1, 0.3, "0.10-0.30"), (0.3, 0.5, "0.30-0.50"),
                           (0.5, 0.7, "0.50-0.70"), (0.7, 0.9, "0.70-0.90"),
                           (0.9, 1.0, ">0.90")]:
        count = ((yp_27 >= lo) & (yp_27 < hi)).sum()
        print(f"    {label}: {count:3d} ({count/len(yp_27)*100:.1f}%)")

    print(f"\n  Above 0.50: {(yp_27 >= 0.50).sum()}")
    print(f"  Above 0.30: {(yp_27 >= 0.30).sum()}")
    print(f"  Above 0.10: {(yp_27 >= 0.10).sum()}")

    # Top 20 pairs
    test_df_out = test_df.copy()
    test_df_out["prob"] = yp_27
    test_df_out = test_df_out.sort_values("prob", ascending=False)

    print(f"\n  Top 30 pairs:")
    for rank, (_, row) in enumerate(test_df_out.head(30).iterrows(), 1):
        print(f"    {rank:>3d}. {row['src_name']:>20s} <-> {row['dst_name']:<20s}  {row['prob']:.4f}")

    # Specific pairs of interest
    print(f"\n  Pairs of interest:")
    interest = [
        ("Drake", "Kendrick Lamar"), ("Daft Punk", "The Weeknd"),
        ("Radiohead", "Tame Impala"), ("The Beatles", "Radiohead"),
        ("Taylor Swift", "Ed Sheeran"), ("Beyonce", "Rihanna"),
        ("Kendrick Lamar", "J. Cole"), ("Travis Scott", "The Weeknd"),
        ("Arctic Monkeys", "Tame Impala"), ("Metallica", "Radiohead"),
    ]
    for a, b in interest:
        mask = ((test_df_out["src_name"] == a) & (test_df_out["dst_name"] == b)) | \
               ((test_df_out["src_name"] == b) & (test_df_out["dst_name"] == a))
        if mask.any():
            p = test_df_out.loc[mask, "prob"].values[0]
            print(f"    {a:>20s} <-> {b:<20s}  {p:.4f}")
        else:
            print(f"    {a:>20s} <-> {b:<20s}  (not found)")

    # Save model
    print(f"\n[8] Saving model...")
    pu_best = best_pipe.named_steps["pu"]
    lr_best = pu_best.estimator
    coef = lr_best.coef_.ravel()
    coef_df = (
        pd.DataFrame({"feature": avail, "coef": coef})
        .assign(abs_coef=lambda d: d.coef.abs())
        .sort_values("abs_coef", ascending=False)
    )

    print(f"  Coefficients:")
    for _, row in coef_df.iterrows():
        print(f"    {row['feature']:30s}  {row['coef']:>8.4f}")
    print(f"  Intercept: {lr_best.intercept_[0]:.4f}")
    print(f"  PU c constant: {pu_best.c:.6f}")

    payload = {
        "model": best_pipe,
        "threshold": final_threshold,
        "feature_names": avail,
        "coef_df": coef_df,
        "pu_method": "elkanoto",
        "n2v_params": {
            "dim": NODE2VEC_DIM, "p": NODE2VEC_P, "q": NODE2VEC_Q,
            "epochs": NODE2VEC_EPOCHS, "walk_length": NODE2VEC_WALK_LENGTH,
            "num_walks": NODE2VEC_NUM_WALKS, "window": NODE2VEC_WINDOW_SIZE,
            "workers": NODE2VEC_WORKERS,
        },
    }
    joblib.dump(payload, MODEL_PATH)
    print(f"  Saved model to: {MODEL_PATH}")

    # Save metadata
    os.makedirs(os.path.dirname(META_PATH), exist_ok=True)

    class NE(json.JSONEncoder):
        def default(self, o):
            if isinstance(o, (np.integer,)): return int(o)
            if isinstance(o, (np.floating,)): return float(o)
            if isinstance(o, np.ndarray): return o.tolist()
            if isinstance(o, np.bool_): return bool(o)
            return super().default(o)

    meta = {
        "model_version": "v7",
        "experiment": "recalibration_final",
        "hypothesis": "C=0.001 (100x stronger regularization than original C=1.0) compresses "
                      "coefficients from max=12.8 to max~2.3, producing spread-out probabilities. "
                      "Threshold set to achieve ~0.9 link recall with meaningful mid-range scores.",
        "n2v_params": payload["n2v_params"],
        "features": avail,
        "threshold": final_threshold,
        "pu_method": "elkanoto",
        "training_params": {
            "C": CHOSEN_C,
            "l1_ratio": CHOSEN_L1,
            "max_iter": 5000,
            "hold_out_ratio": 0.2,
            "num_true_samples": 100000,
            "neg_ratio": 0.30,
            "train_test_split": 0.2,
        },
        "mean_metrics": {
            "roc_auc": round(float(mean["roc_auc"]), 4),
            "precision": round(float(mean["prec"]), 4),
            "link_recall": round(float(mean["link_recall"]), 4),
            "nolink_recall": round(float(mean["nolink_recall"]), 4),
            "balanced_recall": round(float(mean["balanced_recall"]), 4),
        },
        "seed_results": seed_results,
        "test_27_artist_stats": {
            "total_pairs": int(len(yp_27)),
            "above_0.5": int((yp_27 >= 0.5).sum()),
            "above_0.3": int((yp_27 >= 0.3).sum()),
            "above_0.1": int((yp_27 >= 0.1).sum()),
            "prob_mean": round(float(yp_27.mean()), 4),
            "prob_median": round(float(np.median(yp_27)), 4),
            "prob_max": round(float(yp_27.max()), 4),
            "prob_min": round(float(yp_27.min()), 4),
        },
        "coefficients": {
            row["feature"]: round(float(row["coef"]), 6)
            for _, row in coef_df.iterrows()
        },
        "intercept": round(float(lr_best.intercept_[0]), 6),
        "pu_c_constant": round(float(pu_best.c), 6),
        "previous_model_diagnosis": {
            "issue": "C=1.0 produced max coef=12.8 and intercept=3.75, making sigmoid binary. "
                     "Only 2/351 test pairs scored above 0.5. PU c=0.9994 (no correction).",
            "previous_C": 1.0,
            "previous_l1_ratio": 0.3,
            "previous_coef_max": 12.81,
            "previous_pu_c": 0.9994,
        },
        "v6_baseline": {
            "balanced_recall": 0.9283, "precision": 0.9684,
            "link_recall": 0.9613, "nolink_recall": 0.8953, "roc_auc": 0.9839,
        },
        "embeddings_persistent_path": EMBEDDINGS_CSV_PATH,
        "embeddings_db_table": "artist_embeddings_n2v",
    }
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2, cls=NE)
    print(f"  Saved metadata to: {META_PATH}")

    elapsed = time.time() - t_total
    print(f"\n{'=' * 70}")
    print(f"  COMPLETE in {elapsed / 60:.1f} minutes")
    print(f"  C={CHOSEN_C}, l1={CHOSEN_L1}, threshold={final_threshold}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
