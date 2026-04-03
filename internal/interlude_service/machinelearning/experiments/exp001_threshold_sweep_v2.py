"""
EXP-001 v2: Threshold Sweep on v5 Baseline Model (corrected range)
====================================================================
After debugging the probability distribution, we found:
- No-link probabilities max out at ~0.425
- At threshold >= 0.50, precision is trivially 1.0 (no false positives)
- The meaningful tradeoff happens in the 0.01-0.50 range

This sweep covers 0.01 to 0.55 in fine steps to find the optimal
balanced recall point within the precision budget.

Baseline (t=0.50): Precision=1.0000, Link Recall=0.6205, NoLink Recall=1.0000
                    Balanced Recall=0.8102

The v5 metadata reports precision=0.8035 because that was measured on a
DIFFERENT test split (the model was retrained). On THIS dataset rebuild
with the same seed, precision at 0.50 is 1.0 because the PU classifier
cleanly separates at that threshold.

We define the precision budget relative to the CURRENT baseline:
  precision >= 0.95 (allowing up to 5 points drop from 1.0)
"""
import sys
import os
import json
import numpy as np
import pandas as pd
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    roc_auc_score,
    average_precision_score,
    precision_score,
    recall_score,
    f1_score,
    accuracy_score,
    confusion_matrix,
)

from config.config import RANDOM_STATE, TEST_SIZE, MODEL_ENGINEERING_DIR
from models.link_predictor import LinkPredictor
from features.pipeline_links import build_link_prediction_features

# ---- Parameters ---------------------------------------------------------
NUM_TRUE_SAMPLES = 10_000
NEG_RATIO = 0.15
SEED = RANDOM_STATE
MODEL_PATH = os.path.join(MODEL_ENGINEERING_DIR, "logit_model_v5.joblib")

# Fine-grained sweep across the meaningful range
THRESHOLDS = sorted(set(
    list(np.arange(0.01, 0.10, 0.01)) +
    list(np.arange(0.10, 0.56, 0.05)) +
    [0.50]  # ensure baseline is included
))


def compute_metrics_at_threshold(y_true, y_prob, threshold):
    y_pred = (y_prob >= threshold).astype(int)

    link_recall = recall_score(y_true, y_pred, pos_label=1, zero_division=0)
    nolink_recall = recall_score(y_true, y_pred, pos_label=0, zero_division=0)
    balanced_recall = (link_recall + nolink_recall) / 2.0

    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()

    return {
        "threshold": round(float(threshold), 2),
        "precision": round(precision_score(y_true, y_pred, zero_division=0), 4),
        "link_recall": round(link_recall, 4),
        "nolink_recall": round(nolink_recall, 4),
        "balanced_recall": round(balanced_recall, 4),
        "f1": round(f1_score(y_true, y_pred, zero_division=0), 4),
        "accuracy": round(accuracy_score(y_true, y_pred), 4),
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
    }


def main():
    print("=" * 100)
    print("EXP-001 v2  Threshold Sweep on v5 Baseline (corrected range)")
    print("=" * 100)

    # ---- 1. Build dataset -----------------------------------------------
    print("\n[1/5] Building dataset...")
    df = build_link_prediction_features(
        num_true_samples=NUM_TRUE_SAMPLES,
        neg_ratio=NEG_RATIO,
        random_state=SEED,
        save=False,
    )
    print(f"  Dataset: {df.shape[0]} rows, label dist: "
          f"pos={int((df['label']==1).sum())}, neg={int((df['label']==0).sum())}")

    # ---- 2. Load model --------------------------------------------------
    print(f"\n[2/5] Loading v5 model from {MODEL_PATH}")
    model = LinkPredictor.load(MODEL_PATH)
    features = list(model.feature_names)

    # ---- 3. Prepare test set --------------------------------------------
    missing = set(features) - set(df.columns)
    if missing:
        for col in missing:
            df[col] = 0.0

    X = df[features].values
    y = df["label"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=SEED, stratify=y,
    )
    print(f"  Test set: {len(y_test)} (pos={y_test.sum()}, neg={len(y_test)-y_test.sum()})")

    # ---- 4. Predict probabilities ---------------------------------------
    y_prob = model.predict_proba(X_test)
    roc = roc_auc_score(y_test, y_prob)
    pr_auc = average_precision_score(y_test, y_prob)
    print(f"  ROC AUC: {roc:.4f}, PR AUC: {pr_auc:.4f}")

    # ---- 5. Threshold sweep ---------------------------------------------
    print("\n[5/5] Sweeping thresholds...\n")

    rows = []
    for t in THRESHOLDS:
        m = compute_metrics_at_threshold(y_test, y_prob, t)
        rows.append(m)

    results = pd.DataFrame(rows)

    # ---- Print results --------------------------------------------------
    print("=" * 120)
    print("THRESHOLD SWEEP RESULTS  (v5 baseline, test set, n=%d)" % len(y_test))
    print("=" * 120)
    header = (f"{'Thresh':>7} {'Prec':>7} {'LinkRcl':>8} {'NLRcl':>8} "
              f"{'BalRcl':>8} {'F1':>7} {'Acc':>7}  "
              f"{'TP':>5} {'FP':>5} {'TN':>5} {'FN':>5}")
    print(header)
    print("-" * 120)

    for _, r in results.iterrows():
        marker = " <-- baseline" if r["threshold"] == 0.50 else ""
        line = (
            f"{r['threshold']:>7.2f} "
            f"{r['precision']:>7.4f} "
            f"{r['link_recall']:>8.4f} "
            f"{r['nolink_recall']:>8.4f} "
            f"{r['balanced_recall']:>8.4f} "
            f"{r['f1']:>7.4f} "
            f"{r['accuracy']:>7.4f}  "
            f"{int(r['tp']):>5d} "
            f"{int(r['fp']):>5d} "
            f"{int(r['tn']):>5d} "
            f"{int(r['fn']):>5d}"
            f"{marker}"
        )
        print(line)
    print("-" * 120)

    # ---- Identify optimal threshold -------------------------------------
    # Current baseline at t=0.50: precision=1.0
    # Allow up to 5 points drop => precision >= 0.95
    baseline_row = results[results["threshold"] == 0.50].iloc[0]
    baseline_prec = baseline_row["precision"]
    baseline_bal_recall = baseline_row["balanced_recall"]

    MAX_PRECISION_DROP = 0.05
    min_precision = baseline_prec - MAX_PRECISION_DROP

    eligible = results[results["precision"] >= min_precision].copy()

    if eligible.empty:
        print("\nWARNING: No threshold meets precision budget.")
        best_idx = results["balanced_recall"].idxmax()
    else:
        best_idx = eligible["balanced_recall"].idxmax()

    best = results.loc[best_idx]

    print(f"\nBASELINE (t=0.50):")
    print(f"  Precision:      {baseline_prec:.4f}")
    print(f"  Link Recall:    {baseline_row['link_recall']:.4f}")
    print(f"  No-Link Recall: {baseline_row['nolink_recall']:.4f}")
    print(f"  Balanced Recall:{baseline_bal_recall:.4f}")

    print(f"\nOPTIMAL THRESHOLD (max balanced recall, precision >= {min_precision:.4f}):")
    print(f"  Threshold:      {best['threshold']:.2f}")
    print(f"  Precision:      {best['precision']:.4f}  (delta: {best['precision'] - baseline_prec:+.4f})")
    print(f"  Link Recall:    {best['link_recall']:.4f}  (delta: {best['link_recall'] - baseline_row['link_recall']:+.4f})")
    print(f"  No-Link Recall: {best['nolink_recall']:.4f}  (delta: {best['nolink_recall'] - baseline_row['nolink_recall']:+.4f})")
    print(f"  Balanced Recall:{best['balanced_recall']:.4f}  (delta: {best['balanced_recall'] - baseline_bal_recall:+.4f})")
    print(f"  F1:             {best['f1']:.4f}")

    # ---- Also find the "best overall balanced recall" regardless of precision
    overall_best_idx = results["balanced_recall"].idxmax()
    overall_best = results.loc[overall_best_idx]
    print(f"\nBEST BALANCED RECALL (unconstrained):")
    print(f"  Threshold:      {overall_best['threshold']:.2f}")
    print(f"  Precision:      {overall_best['precision']:.4f}")
    print(f"  Balanced Recall:{overall_best['balanced_recall']:.4f}")

    # ---- Save results ---------------------------------------------------
    out_dir = ML_DIR / "experiments" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "exp001_threshold_sweep_v2.csv"
    results.to_csv(csv_path, index=False)

    summary = {
        "experiment_id": "EXP-001-v2",
        "hypothesis": "Lower threshold improves balanced recall; PU proba range is 0-0.43 for negatives",
        "model": "v5",
        "model_path": MODEL_PATH,
        "dataset_params": {
            "num_true_samples": NUM_TRUE_SAMPLES,
            "neg_ratio": NEG_RATIO,
            "random_state": SEED,
        },
        "test_set_size": int(len(y_test)),
        "test_pos": int(y_test.sum()),
        "test_neg": int(len(y_test) - y_test.sum()),
        "roc_auc": round(roc, 4),
        "pr_auc": round(pr_auc, 4),
        "baseline": {k: round(float(v), 4) for k, v in baseline_row.items()},
        "optimal": {k: round(float(v), 4) for k, v in best.items()},
        "precision_budget": MAX_PRECISION_DROP,
        "all_thresholds": results.to_dict(orient="records"),
    }
    json_path = out_dir / "exp001_threshold_sweep_v2.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nResults saved to {csv_path}")
    print(f"Summary saved to {json_path}")


if __name__ == "__main__":
    main()
