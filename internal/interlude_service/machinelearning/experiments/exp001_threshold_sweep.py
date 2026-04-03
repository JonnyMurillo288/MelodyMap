"""
EXP-001: Threshold Sweep on v5 Baseline Model
===============================================
Hypothesis: The default threshold of 0.50 is not optimal for balanced recall.
            A lower threshold may improve No-Link recall and balanced recall
            within the precision budget (max 2-5 point drop from baseline 0.8035).

Procedure:
1. Rebuild the dataset with the same parameters used for v5 training
   (num_true_samples=10000, neg_ratio=0.15, random_state=42)
2. Load the saved v5 model
3. Split train/test identically (test_size=0.2, random_state=42, stratified)
4. Compute predicted probabilities on the test set
5. Sweep thresholds from 0.20 to 0.70 in steps of 0.05
6. Report metrics at each threshold
"""
import sys
import os
import json
import numpy as np
import pandas as pd
from pathlib import Path

# -- path setup so imports resolve ----------------------------------------
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
)

from config.config import (
    LINK_PREDICTION_FEATURES,
    RANDOM_STATE,
    TEST_SIZE,
    MODEL_ENGINEERING_DIR,
)
from models.link_predictor import LinkPredictor
from features.pipeline_links import build_link_prediction_features


# ---- Parameters (locked to v5 training) --------------------------------
NUM_TRUE_SAMPLES = 10_000
NEG_RATIO = 0.15
SEED = RANDOM_STATE          # 42
SPLIT_TEST_SIZE = TEST_SIZE  # 0.2
MODEL_PATH = os.path.join(MODEL_ENGINEERING_DIR, "logit_model_v5.joblib")
THRESHOLDS = np.arange(0.20, 0.71, 0.05)


def compute_metrics_at_threshold(y_true, y_prob, threshold):
    """Return a dict of metrics for a given threshold."""
    y_pred = (y_prob >= threshold).astype(int)

    # Per-class recall
    link_mask = y_true == 1
    nolink_mask = y_true == 0

    link_recall = recall_score(y_true, y_pred, pos_label=1, zero_division=0)
    nolink_recall = recall_score(y_true, y_pred, pos_label=0, zero_division=0)
    balanced_recall = (link_recall + nolink_recall) / 2.0

    return {
        "threshold": round(float(threshold), 2),
        "precision": round(precision_score(y_true, y_pred, zero_division=0), 4),
        "link_recall": round(link_recall, 4),
        "nolink_recall": round(nolink_recall, 4),
        "balanced_recall": round(balanced_recall, 4),
        "f1": round(f1_score(y_true, y_pred, zero_division=0), 4),
        "accuracy": round(accuracy_score(y_true, y_pred), 4),
    }


def main():
    print("=" * 72)
    print("EXP-001  Threshold Sweep on v5 Baseline")
    print("=" * 72)

    # ---- 1. Build dataset (same params as v5 training) ------------------
    print("\n[1/5] Building dataset (num_true_samples=%d, neg_ratio=%.2f, seed=%d)..."
          % (NUM_TRUE_SAMPLES, NEG_RATIO, SEED))
    df = build_link_prediction_features(
        num_true_samples=NUM_TRUE_SAMPLES,
        neg_ratio=NEG_RATIO,
        random_state=SEED,
        save=False,   # do not overwrite the CSV on disk
    )

    print(f"  Dataset shape: {df.shape}")
    print(f"  Label distribution:\n{df['label'].value_counts().to_string()}")

    # ---- 2. Load v5 model -----------------------------------------------
    print(f"\n[2/5] Loading v5 model from {MODEL_PATH}")
    model = LinkPredictor.load(MODEL_PATH)
    features = list(model.feature_names)
    print(f"  Model features ({len(features)}): {features}")
    print(f"  Model threshold (default): {model.threshold}")

    # ---- 3. Align features and split ------------------------------------
    print("\n[3/5] Preparing feature matrix and train/test split...")
    # Make sure all model features are present
    missing = set(features) - set(df.columns)
    if missing:
        print(f"  WARNING: missing features {missing} -- filling with 0")
        for col in missing:
            df[col] = 0.0

    X = df[features].values
    y = df["label"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=SPLIT_TEST_SIZE,
        random_state=SEED,
        stratify=y,
    )
    print(f"  Train: {len(y_train)}  (pos={y_train.sum()}, neg={len(y_train)-y_train.sum()})")
    print(f"  Test:  {len(y_test)}  (pos={y_test.sum()}, neg={len(y_test)-y_test.sum()})")

    # ---- 4. Predict probabilities on test set ---------------------------
    print("\n[4/5] Generating predicted probabilities on test set...")
    y_prob = model.predict_proba(X_test)
    roc = roc_auc_score(y_test, y_prob)
    pr_auc = average_precision_score(y_test, y_prob)
    print(f"  ROC AUC: {roc:.4f}")
    print(f"  PR  AUC: {pr_auc:.4f}")

    # ---- 5. Threshold sweep ---------------------------------------------
    print("\n[5/5] Sweeping thresholds from %.2f to %.2f (step 0.05)..." %
          (THRESHOLDS[0], THRESHOLDS[-1]))

    rows = []
    for t in THRESHOLDS:
        m = compute_metrics_at_threshold(y_test, y_prob, t)
        rows.append(m)

    results = pd.DataFrame(rows)

    # ---- Print results table --------------------------------------------
    print("\n" + "=" * 96)
    print("THRESHOLD SWEEP RESULTS  (v5 baseline, test set)")
    print("=" * 96)
    header = f"{'Threshold':>10} {'Precision':>10} {'Link Rcl':>10} {'NoLink Rcl':>12} {'Bal Rcl':>10} {'F1':>8} {'Accuracy':>10}"
    print(header)
    print("-" * 96)
    for _, r in results.iterrows():
        line = (
            f"{r['threshold']:>10.2f} "
            f"{r['precision']:>10.4f} "
            f"{r['link_recall']:>10.4f} "
            f"{r['nolink_recall']:>12.4f} "
            f"{r['balanced_recall']:>10.4f} "
            f"{r['f1']:>8.4f} "
            f"{r['accuracy']:>10.4f}"
        )
        print(line)
    print("-" * 96)

    # ---- Identify optimal threshold -------------------------------------
    BASELINE_PRECISION = 0.8035
    MAX_PRECISION_DROP = 0.05  # 5 points

    eligible = results[results["precision"] >= (BASELINE_PRECISION - MAX_PRECISION_DROP)]
    if eligible.empty:
        print("\nWARNING: No threshold meets the precision budget.")
        best_idx = results["balanced_recall"].idxmax()
    else:
        best_idx = eligible["balanced_recall"].idxmax()

    best = results.loc[best_idx]
    print(f"\nOPTIMAL THRESHOLD (max balanced recall within precision budget):")
    print(f"  Threshold:      {best['threshold']:.2f}")
    print(f"  Precision:      {best['precision']:.4f}  (baseline: {BASELINE_PRECISION:.4f}, delta: {best['precision'] - BASELINE_PRECISION:+.4f})")
    print(f"  Link Recall:    {best['link_recall']:.4f}")
    print(f"  No-Link Recall: {best['nolink_recall']:.4f}")
    print(f"  Balanced Recall:{best['balanced_recall']:.4f}")
    print(f"  F1:             {best['f1']:.4f}")
    print(f"  Accuracy:       {best['accuracy']:.4f}")

    # ---- Save results ---------------------------------------------------
    out_dir = ML_DIR / "experiments" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "exp001_threshold_sweep.csv"
    results.to_csv(csv_path, index=False)
    print(f"\nResults saved to {csv_path}")

    summary = {
        "experiment_id": "EXP-001",
        "hypothesis": "Lower threshold improves balanced recall within precision budget",
        "model": "v5",
        "model_path": MODEL_PATH,
        "dataset_params": {
            "num_true_samples": NUM_TRUE_SAMPLES,
            "neg_ratio": NEG_RATIO,
            "random_state": SEED,
        },
        "test_set_size": int(len(y_test)),
        "roc_auc": round(roc, 4),
        "pr_auc": round(pr_auc, 4),
        "baseline_threshold": 0.50,
        "baseline_precision": BASELINE_PRECISION,
        "optimal_threshold": round(float(best["threshold"]), 2),
        "optimal_metrics": {k: round(float(v), 4) for k, v in best.items()},
    }
    json_path = out_dir / "exp001_threshold_sweep.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Summary saved to {json_path}")


if __name__ == "__main__":
    main()
