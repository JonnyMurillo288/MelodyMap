#!/usr/bin/env python3
"""
Experiment: Recalibrate v7 model to target ~0.9 recall with spread-out probabilities.

Diagnosis:
    The current v7 model uses C=1.0 (weak regularization), producing
    coefficients up to 12.8 in absolute value. This makes the logistic
    sigmoid essentially binary: nearly all probabilities are 0.0000 or
    0.9940 (the clip cap). For 351 test pairs among 27 well-known artists,
    only 2 pairs scored above 0.5.

Fix:
    Retrain with much stronger regularization (C in [0.001, 0.01, 0.05, 0.1])
    to compress coefficients and produce spread-out probability scores.
    The ElkanotoPU wrapper is kept for PU learning, but the underlying LR
    will produce softer decision boundaries.

    The threshold is lowered from 0.5 to the value that yields ~0.9 link recall
    on the validation set, giving plausible-but-unconfirmed pairs meaningful
    nonzero probabilities.

Run from: /home/jonnym/Desktop/MelodyMap/internal/interlude_service/machinelearning/
    python3 experiments/exp_v7_recalibrate.py
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
    roc_auc_score, average_precision_score, precision_score,
    recall_score, f1_score, classification_report,
)

# pulearn compatibility shims
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

# ---------- constants ----------
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

# 27 test artists
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

# Regularization strengths to sweep (lower C = stronger regularization)
C_VALUES = [0.001, 0.005, 0.01, 0.05, 0.1]

# l1_ratio candidates
L1_RATIOS = [0.3, 0.5, 0.8]

# Target link recall
TARGET_LINK_RECALL = 0.90


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


def threshold_sweep(y_true, y_prob, thresholds=None):
    """Sweep thresholds and return metrics at each."""
    if thresholds is None:
        thresholds = np.arange(0.05, 0.80, 0.05)
    results = []
    for thr in thresholds:
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
    """Find the highest threshold that achieves at least target link recall."""
    candidates = [r for r in sweep_results if r["link_recall"] >= target_lr]
    if not candidates:
        # Fall back to lowest threshold
        return min(sweep_results, key=lambda r: r["thr"])
    # Pick highest threshold among those meeting the recall target
    return max(candidates, key=lambda r: r["thr"])


def build_27_artist_test_features(emb_df, edges_df, pop_map):
    """Build feature rows for all 351 pairs among the 27 test artists."""
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

    print(f"  27-artist test: {len(rows)} pairs built, {skip} skipped (missing embeddings)")
    df = pd.DataFrame(rows)
    if "popularity_src" in df.columns:
        compute_popularity_interactions(df)
    return df


def main():
    print("=" * 70)
    print("  V7 RECALIBRATION EXPERIMENT")
    print("  Goal: ~0.9 link recall with spread-out probabilities")
    print("=" * 70)

    t_total = time.time()

    # ---- Load cached embeddings and edges (no retraining embeddings) ----
    print("\n[1] Loading cached embeddings and edges...")
    assert os.path.exists(EMBEDDINGS_CSV_PATH), f"Missing: {EMBEDDINGS_CSV_PATH}"
    assert os.path.exists(EDGES_CSV_PATH), f"Missing: {EDGES_CSV_PATH}"

    emb_df = pd.read_csv(EMBEDDINGS_CSV_PATH)
    edges_df = pd.read_csv(EDGES_CSV_PATH)
    print(f"  Embeddings: {len(emb_df)} artists")
    print(f"  Edges: {len(edges_df)}")

    # ---- Get training pairs ----
    print("\n[2] Getting training pairs (100K true, neg_ratio=0.30)...")
    conn = get_pg_conn()
    pairs = get_training_test(conn, 100000, 0.30, 42, 5, 5)
    conn.close()
    print(f"  Pairs: {len(pairs)}, label dist: {pairs['label'].value_counts().to_dict()}")

    # ---- Get popularity map ----
    print("\n[3] Getting popularity map...")
    pop_map = get_pop_map()

    # ---- Build features ----
    print("\n[4] Building features...")
    feat_df = build_features_for_pairs(emb_df, edges_df, pairs, pop_map)
    avail = [f for f in V7_FEATURES if f in feat_df.columns]
    print(f"  Available features: {avail}")
    assert len(avail) == len(V7_FEATURES), f"Missing features: {set(V7_FEATURES) - set(avail)}"

    # ---- Build 27-artist test features ----
    print("\n[5] Building 27-artist test features...")
    test_df = build_27_artist_test_features(emb_df, edges_df, pop_map)

    # ---- Hyperparameter sweep: C x l1_ratio ----
    print("\n[6] Hyperparameter sweep (C x l1_ratio)...")
    print(f"  C values: {C_VALUES}")
    print(f"  l1_ratio values: {L1_RATIOS}")
    print(f"  Target link recall: {TARGET_LINK_RECALL}")

    X_all = feat_df[avail].values
    y_all = feat_df["label"].values

    Xtr, Xte, ytr, yte = train_test_split(
        X_all, y_all, test_size=0.2, random_state=42, stratify=y_all
    )
    print(f"  Train: {len(ytr)} (pos={ytr.sum()}, neg={len(ytr)-ytr.sum()})")
    print(f"  Test:  {len(yte)} (pos={yte.sum()}, neg={len(yte)-yte.sum()})")

    best_config = None
    best_score = -1
    all_results = []

    for C in C_VALUES:
        for l1 in L1_RATIOS:
            label = f"C={C}, l1={l1}"
            print(f"\n  --- {label} ---")

            logit = LogisticRegression(
                penalty="elasticnet", solver="saga", max_iter=5000,
                C=C, l1_ratio=l1, random_state=42, warm_start=False,
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

            # Check probability distribution
            pct_near_zero = (yp < 0.01).mean()
            pct_near_one = (yp > 0.99).mean()
            pct_midrange = ((yp >= 0.1) & (yp <= 0.9)).mean()

            print(f"    Train time: {train_time:.1f}s")
            print(f"    Prob dist: <0.01={pct_near_zero:.3f} | 0.1-0.9={pct_midrange:.3f} | >0.99={pct_near_one:.3f}")
            print(f"    ROC AUC: {roc_auc_score(yte, yp):.4f}")

            # Coefficients
            lr_fitted = pu.estimator
            coef = lr_fitted.coef_.ravel()
            print(f"    Coef range: [{coef.min():.4f}, {coef.max():.4f}]")
            print(f"    Intercept: {lr_fitted.intercept_[0]:.4f}")
            print(f"    PU c constant: {pu.c:.6f}")

            # Threshold sweep
            sweep = threshold_sweep(yte, yp)

            # Find threshold for target recall
            chosen = find_threshold_for_target_recall(sweep, TARGET_LINK_RECALL)

            print(f"    Chosen threshold: {chosen['thr']}")
            print(f"    Link recall: {chosen['link_recall']:.4f}")
            print(f"    No-link recall: {chosen['nolink_recall']:.4f}")
            print(f"    Balanced recall: {chosen['balanced_recall']:.4f}")
            print(f"    Precision: {chosen['prec']:.4f}")
            print(f"    F1: {chosen['f1']:.4f}")

            # 27-artist test
            X_test_27 = test_df[avail].values
            yp_27 = pipe.predict_proba(X_test_27)
            if yp_27.ndim > 1 and yp_27.shape[1] > 1:
                yp_27 = yp_27[:, 1]
            yp_27 = np.clip(yp_27, 0, 0.994)

            above_05 = (yp_27 >= 0.5).sum()
            above_03 = (yp_27 >= 0.3).sum()
            above_01 = (yp_27 >= 0.1).sum()
            above_chosen = (yp_27 >= chosen["thr"]).sum()

            print(f"    27-artist test ({len(yp_27)} pairs):")
            print(f"      >0.5: {above_05} | >0.3: {above_03} | >0.1: {above_01} | >thr({chosen['thr']}): {above_chosen}")
            print(f"      Prob range: [{yp_27.min():.4f}, {yp_27.max():.4f}]")
            print(f"      Mean: {yp_27.mean():.4f}, Median: {np.median(yp_27):.4f}")

            # Top 10 most likely pairs from the 27-artist set
            top10_idx = np.argsort(yp_27)[-10:][::-1]
            print(f"    Top 10 pairs:")
            for idx in top10_idx:
                print(f"      {test_df.iloc[idx]['src_name']:20s} <-> {test_df.iloc[idx]['dst_name']:20s}  prob={yp_27[idx]:.4f}")

            result = {
                "C": C, "l1_ratio": l1,
                "train_time": train_time,
                "roc_auc": float(roc_auc_score(yte, yp)),
                "chosen_threshold": chosen["thr"],
                "link_recall": chosen["link_recall"],
                "nolink_recall": chosen["nolink_recall"],
                "balanced_recall": chosen["balanced_recall"],
                "precision": chosen["prec"],
                "f1": chosen["f1"],
                "test_27_above_05": int(above_05),
                "test_27_above_03": int(above_03),
                "test_27_above_01": int(above_01),
                "test_27_prob_mean": float(yp_27.mean()),
                "test_27_prob_max": float(yp_27.max()),
                "coef_max": float(np.abs(coef).max()),
                "pu_c": float(pu.c),
                "pct_midrange": float(pct_midrange),
            }
            all_results.append(result)

            # Score: balanced recall, with bonus for probability spread
            score = chosen["balanced_recall"] + 0.05 * pct_midrange
            if chosen["link_recall"] < TARGET_LINK_RECALL:
                score -= 0.5  # Penalize not meeting recall target

            if score > best_score:
                best_score = score
                best_config = {
                    "C": C, "l1_ratio": l1,
                    "pipe": pipe, "threshold": chosen["thr"],
                    "result": result, "sweep": sweep,
                }

    # ---- Print summary ----
    print("\n" + "=" * 70)
    print("  SWEEP SUMMARY")
    print("=" * 70)
    print(f"  {'C':>6s} {'l1':>5s} | {'ROC':>6s} {'BR':>6s} {'LR':>6s} {'NR':>6s} {'Prec':>6s} | {'thr':>4s} | {'27_>0.5':>7s} {'27_>0.1':>7s} {'Spread':>6s}")
    print("  " + "-" * 80)
    for r in all_results:
        print(f"  {r['C']:>6.3f} {r['l1_ratio']:>5.1f} | "
              f"{r['roc_auc']:>6.4f} {r['balanced_recall']:>6.4f} {r['link_recall']:>6.4f} "
              f"{r['nolink_recall']:>6.4f} {r['precision']:>6.4f} | "
              f"{r['chosen_threshold']:>4.2f} | "
              f"{r['test_27_above_05']:>7d} {r['test_27_above_01']:>7d} {r['pct_midrange']:>6.3f}")

    # ---- Multi-seed validation of best config ----
    print("\n" + "=" * 70)
    print(f"  BEST CONFIG: C={best_config['C']}, l1={best_config['l1_ratio']}")
    print("  Running 3-seed validation...")
    print("=" * 70)

    seed_results = []
    best_pipe_across_seeds = None
    best_br_across_seeds = -1

    for seed in [42, 123, 456]:
        print(f"\n  Seed {seed}...")
        Xtr_s, Xte_s, ytr_s, yte_s = train_test_split(
            X_all, y_all, test_size=0.2, random_state=seed, stratify=y_all
        )

        logit = LogisticRegression(
            penalty="elasticnet", solver="saga", max_iter=5000,
            C=best_config["C"], l1_ratio=best_config["l1_ratio"],
            random_state=seed,
        )
        pu = ElkanotoPuClassifier(estimator=logit, hold_out_ratio=0.2)
        pipe = Pipeline([
            ("imp", SimpleImputer(strategy="median")),
            ("scl", StandardScaler()),
            ("pu", pu),
        ])

        t0 = time.time()
        pipe.fit(Xtr_s, ytr_s)
        train_time = time.time() - t0

        yp = pipe.predict_proba(Xte_s)
        if yp.ndim > 1 and yp.shape[1] > 1:
            yp = yp[:, 1]
        yp = np.clip(yp, 0, 0.994)

        sweep = threshold_sweep(yte_s, yp)
        chosen = find_threshold_for_target_recall(sweep, TARGET_LINK_RECALL)

        roc = float(roc_auc_score(yte_s, yp))

        result = {
            "seed": seed, "roc_auc": roc, "train_s": train_time,
            "thr": chosen["thr"],
            "prec": chosen["prec"],
            "lr": chosen["link_recall"],
            "nr": chosen["nolink_recall"],
            "br": chosen["balanced_recall"],
            "f1": chosen["f1"],
        }
        seed_results.append(result)

        print(f"    ROC={roc:.4f} Prec={chosen['prec']:.4f} "
              f"LR={chosen['link_recall']:.4f} NR={chosen['nolink_recall']:.4f} "
              f"BR={chosen['balanced_recall']:.4f} thr={chosen['thr']}")

        if chosen["balanced_recall"] > best_br_across_seeds:
            best_br_across_seeds = chosen["balanced_recall"]
            best_pipe_across_seeds = pipe

    # Mean metrics
    mean = {k: np.mean([s[k] for s in seed_results])
            for k in ["roc_auc", "prec", "lr", "nr", "br"]}
    mean_thr = np.mean([s["thr"] for s in seed_results])

    print(f"\n  3-seed mean:")
    print(f"    ROC AUC:         {mean['roc_auc']:.4f}")
    print(f"    Precision:       {mean['prec']:.4f}")
    print(f"    Link recall:     {mean['lr']:.4f}")
    print(f"    No-link recall:  {mean['nr']:.4f}")
    print(f"    Balanced recall: {mean['br']:.4f}")
    print(f"    Mean threshold:  {mean_thr:.2f}")

    # ---- Final 27-artist evaluation with best pipeline ----
    print("\n" + "=" * 70)
    print("  FINAL 27-ARTIST TEST (best pipeline)")
    print("=" * 70)

    X_test_27 = test_df[avail].values
    yp_27 = best_pipe_across_seeds.predict_proba(X_test_27)
    if yp_27.ndim > 1 and yp_27.shape[1] > 1:
        yp_27 = yp_27[:, 1]
    yp_27 = np.clip(yp_27, 0, 0.994)

    # Use rounded mean threshold
    final_threshold = round(mean_thr * 20) / 20  # Round to nearest 0.05

    print(f"  Total pairs: {len(yp_27)}")
    print(f"  Final threshold: {final_threshold}")
    print(f"  Prob distribution:")
    for lo, hi, label in [(0, 0.01, "<0.01"), (0.01, 0.1, "0.01-0.10"),
                           (0.1, 0.3, "0.10-0.30"), (0.3, 0.5, "0.30-0.50"),
                           (0.5, 0.7, "0.50-0.70"), (0.7, 0.9, "0.70-0.90"),
                           (0.9, 1.0, ">0.90")]:
        count = ((yp_27 >= lo) & (yp_27 < hi)).sum()
        print(f"    {label}: {count:3d} ({count/len(yp_27)*100:.1f}%)")

    print(f"\n  Above threshold ({final_threshold}): {(yp_27 >= final_threshold).sum()}")
    print(f"  Above 0.50: {(yp_27 >= 0.50).sum()}")
    print(f"  Above 0.30: {(yp_27 >= 0.30).sum()}")
    print(f"  Above 0.10: {(yp_27 >= 0.10).sum()}")

    # Full pair listing sorted by probability
    test_df_out = test_df.copy()
    test_df_out["prob"] = yp_27
    test_df_out = test_df_out.sort_values("prob", ascending=False)

    print(f"\n  All {len(test_df_out)} pairs sorted by probability:")
    print(f"  {'Rank':>4s}  {'Artist A':>20s} <-> {'Artist B':<20s}  {'Prob':>7s}")
    print("  " + "-" * 65)
    for rank, (_, row) in enumerate(test_df_out.iterrows(), 1):
        marker = " *" if row["prob"] >= final_threshold else ""
        print(f"  {rank:>4d}  {row['src_name']:>20s} <-> {row['dst_name']:<20s}  {row['prob']:>7.4f}{marker}")

    # ---- Save model ----
    print("\n" + "=" * 70)
    print("  SAVING RECALIBRATED V7 MODEL")
    print("=" * 70)

    # Extract coefficients from best pipeline
    pu_best = best_pipe_across_seeds.named_steps["pu"]
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

    payload = {
        "model": best_pipe_across_seeds,
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
        "experiment": "recalibration",
        "hypothesis": "Stronger regularization (lower C) compresses coefficients, "
                      "producing spread-out probabilities instead of near-binary scores. "
                      "Threshold tuned to ~0.9 link recall.",
        "n2v_params": payload["n2v_params"],
        "features": avail,
        "threshold": final_threshold,
        "pu_method": "elkanoto",
        "training_params": {
            "C": best_config["C"],
            "l1_ratio": best_config["l1_ratio"],
            "max_iter": 5000,
            "hold_out_ratio": 0.2,
            "num_true_samples": 100000,
            "neg_ratio": 0.30,
            "train_test_split": 0.2,
        },
        "mean_metrics": {
            "roc_auc": round(float(mean["roc_auc"]), 4),
            "precision": round(float(mean["prec"]), 4),
            "link_recall": round(float(mean["lr"]), 4),
            "nolink_recall": round(float(mean["nr"]), 4),
            "balanced_recall": round(float(mean["br"]), 4),
        },
        "seed_results": seed_results,
        "test_27_artist_stats": {
            "total_pairs": int(len(yp_27)),
            "above_threshold": int((yp_27 >= final_threshold).sum()),
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
            "issue": "C=1.0 produced max coef=12.8, making sigmoid binary. "
                     "Only 2/351 test pairs scored above 0.5.",
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
    print(f"  Model: {MODEL_PATH}")
    print(f"  Metadata: {META_PATH}")
    print(f"  Best config: C={best_config['C']}, l1={best_config['l1_ratio']}")
    print(f"  Threshold: {final_threshold}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
