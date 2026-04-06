"""
v8 Link Predictor — Training & Evaluation Script

Experiments combined:
  v8a: Relaxed regularization (C in [0.01, 0.1, 1.0]) — reactivates geometry/popularity features
  v8b: Genre similarity features (rosamerica) added to feature set
  v8c: Lowered decision threshold (0.35) for exploration UX
  v8d: Connection potential score transformation (0-100 scale)

Usage:
    cd internal/interlude_service/machinelearning
    python train_v8.py
"""
import os
import sys
import json
import time
import numpy as np
import pandas as pd
from pathlib import Path

from config.config import (
    FEATURE_GROUPS,
    GENRE_TYPE_CLASSIFICATION,
    LINK_PREDICTION_FEATURES,
    LOGIT_L1_RATIOS,
    LOGIT_THRESHOLD,
    TEST_SIZE,
    RANDOM_STATE,
    MODEL_ENGINEERING_DIR,
    ARTIST_COLLAB_NEG_CSV,
    LOGIT_MODEL_VERSION,
    LOGIT_MODEL_ID,
    LOGIT_MODEL_DESC,
)
from features.pipeline_links import (
    build_link_prediction_features,
    genre_type_proportions_column_names,
)
from models.link_predictor import LinkPredictor, train_link_predictor
from models import artist_similarity as art_sim

from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    roc_auc_score,
    average_precision_score,
    precision_score,
    recall_score,
    f1_score,
    classification_report,
)


# ── v6 / v7 baselines (from metadata JSONs) ──────────────────────
V6_BASELINE = {
    "balanced_recall": 0.9283,
    "precision": 0.9684,
    "link_recall": 0.9613,
    "nolink_recall": 0.8953,
    "roc_auc": 0.9839,
}

V7_BASELINE = {
    "balanced_recall": 0.9967,
    "precision": 0.998,
    "link_recall": 1.0,
    "nolink_recall": 0.9934,
    "roc_auc": 1.0,
}


def threshold_sweep(model, X_test, y_test, thresholds=None):
    """Evaluate model at multiple thresholds and return a metrics table."""
    if thresholds is None:
        thresholds = np.arange(0.20, 0.75, 0.05)

    y_prob = model.predict_proba(X_test)
    rows = []
    for thr in thresholds:
        y_pred = (y_prob >= thr).astype(int)
        link_mask = y_test == 1
        nolink_mask = y_test == 0
        link_recall = recall_score(y_test[link_mask], y_pred[link_mask], zero_division=0) if link_mask.sum() > 0 else 0.0
        nolink_recall = recall_score(1 - y_test[nolink_mask], 1 - y_pred[nolink_mask], zero_division=0) if nolink_mask.sum() > 0 else 0.0

        rows.append({
            "threshold": round(thr, 2),
            "precision": precision_score(y_test, y_pred, zero_division=0),
            "link_recall": (y_pred[link_mask] == 1).mean() if link_mask.sum() > 0 else 0.0,
            "nolink_recall": (y_pred[nolink_mask] == 0).mean() if nolink_mask.sum() > 0 else 0.0,
            "balanced_recall": ((y_pred[link_mask] == 1).mean() + (y_pred[nolink_mask] == 0).mean()) / 2
                if link_mask.sum() > 0 and nolink_mask.sum() > 0 else 0.0,
            "f1": f1_score(y_test, y_pred, zero_division=0),
        })
    return pd.DataFrame(rows)


def run_seed_experiment(df, features, seed, C_values, threshold):
    """Train and evaluate on one seed. Returns metrics dict."""
    X_all = df[features]
    y_all = df["label"]

    X_train, X_test, y_train, y_test = train_test_split(
        X_all.values, y_all.values,
        test_size=TEST_SIZE,
        random_state=seed,
        stratify=y_all.values,
    )

    t0 = time.time()
    model = LinkPredictor(
        pu_method="elkanoto",
        Cs=C_values,
        l1_ratios=LOGIT_L1_RATIOS,
        threshold=threshold,
        scoring="f1",
        n_iter=10,
        cv=3,
        random_state=seed,
    )
    model.fit(X_train, y_train, feature_names=features)
    train_time = time.time() - t0

    # Evaluate
    y_prob = model.predict_proba(X_test)
    y_pred = model.predict(X_test)

    link_mask = y_test == 1
    nolink_mask = y_test == 0

    roc = roc_auc_score(y_test, y_prob)
    pr = average_precision_score(y_test, y_prob)
    prec = precision_score(y_test, y_pred, zero_division=0)
    link_rec = (y_pred[link_mask] == 1).mean() if link_mask.sum() > 0 else 0.0
    nolink_rec = (y_pred[nolink_mask] == 0).mean() if nolink_mask.sum() > 0 else 0.0
    bal_rec = (link_rec + nolink_rec) / 2
    f1 = f1_score(y_test, y_pred, zero_division=0)

    # Score transformation demo
    sample_probs = np.array([0.05, 0.15, 0.30, 0.50, 0.70, 0.90, 0.99])
    potential_scores = LinkPredictor.connection_potential_score(sample_probs)

    info = model.get_model_info()
    best_params = info["best_params"]

    return {
        "seed": seed,
        "roc_auc": roc,
        "pr_auc": pr,
        "train_s": train_time,
        "thr": threshold,
        "prec": prec,
        "link_recall": link_rec,
        "nolink_recall": nolink_rec,
        "balanced_recall": bal_rec,
        "f1": f1,
        "best_C": best_params.get("pu_logit__estimator__C"),
        "best_l1": best_params.get("pu_logit__estimator__l1_ratio"),
        "score_transform_demo": dict(zip(sample_probs.tolist(), potential_scores.tolist())),
    }, model, X_test, y_test


def main():
    print("=" * 70)
    print("v8 Link Predictor — Training & Evaluation")
    print("=" * 70)

    # ── Step 1: Build dataset ──────────────────────────────────────
    print("\n[1/5] Building training dataset...")
    num_true_samples = 100_000
    neg_ratio = 0.3

    df = build_link_prediction_features(
        num_true_samples=num_true_samples,
        neg_ratio=neg_ratio,
        random_state=RANDOM_STATE,
        save=True,
    )

    # Add genre similarity via artist_similarity module
    gt = genre_type_proportions_column_names(GENRE_TYPE_CLASSIFICATION)
    gt_sim = ["similarity_prop_" + g for g in gt]

    print(f"Dataset shape: {df.shape}")
    print(f"Label distribution:\n{df['label'].value_counts()}")
    print(f"Genre features present: {[c for c in df.columns if 'similarity' in c]}")

    # ── Step 2: Validate features ──────────────────────────────────
    features = list(LINK_PREDICTION_FEATURES)

    # Check which features are actually available
    missing = [f for f in features if f not in df.columns]
    available = [f for f in features if f in df.columns]
    if missing:
        print(f"\n⚠ Missing features (will train without): {missing}")
        features = available

    print(f"\n[2/5] Feature set ({len(features)} features):")
    for f in features:
        print(f"  - {f}")

    # ── Step 3: Multi-seed training ────────────────────────────────
    print("\n[3/5] Multi-seed validation (seeds: 42, 123, 456)...")

    C_values = [0.01, 0.1, 1.0]  # v8a: relaxed regularization range
    threshold = LOGIT_THRESHOLD   # v8c: 0.35

    seed_results = []
    best_model = None
    best_X_test = None
    best_y_test = None

    for seed in [42, 123, 456]:
        print(f"\n  --- Seed {seed} ---")
        result, model, X_test, y_test = run_seed_experiment(
            df, features, seed, C_values, threshold
        )
        seed_results.append(result)
        print(f"  ROC AUC:        {result['roc_auc']:.6f}")
        print(f"  Precision:      {result['prec']:.4f}")
        print(f"  Link Recall:    {result['link_recall']:.4f}")
        print(f"  No-Link Recall: {result['nolink_recall']:.4f}")
        print(f"  Balanced Recall:{result['balanced_recall']:.4f}")
        print(f"  F1:             {result['f1']:.4f}")
        print(f"  Best C:         {result['best_C']}")
        print(f"  Best l1_ratio:  {result['best_l1']}")
        print(f"  Train time:     {result['train_s']:.1f}s")

        if seed == 42:
            best_model = model
            best_X_test = X_test
            best_y_test = y_test

    # ── Step 4: Threshold sweep on seed=42 model ───────────────────
    print("\n[4/5] Threshold sweep (seed=42 model):")
    sweep_df = threshold_sweep(best_model, best_X_test, best_y_test)
    print(sweep_df.to_string(index=False, float_format="%.4f"))

    # ── Step 5: Comparison and score demo ──────────────────────────
    mean_metrics = {
        "roc_auc": np.mean([r["roc_auc"] for r in seed_results]),
        "precision": np.mean([r["prec"] for r in seed_results]),
        "link_recall": np.mean([r["link_recall"] for r in seed_results]),
        "nolink_recall": np.mean([r["nolink_recall"] for r in seed_results]),
        "balanced_recall": np.mean([r["balanced_recall"] for r in seed_results]),
    }

    print("\n[5/5] Results comparison:")
    print(f"\n{'Metric':<20} {'v6':>10} {'v7':>10} {'v8 (mean)':>10} {'v8 vs v6':>10} {'v8 vs v7':>10}")
    print("-" * 70)
    for metric in ["roc_auc", "precision", "link_recall", "nolink_recall", "balanced_recall"]:
        v6 = V6_BASELINE.get(metric, 0)
        v7 = V7_BASELINE.get(metric, 0)
        v8 = mean_metrics[metric]
        print(f"{metric:<20} {v6:>10.4f} {v7:>10.4f} {v8:>10.4f} {v8 - v6:>+10.4f} {v8 - v7:>+10.4f}")

    # Score transformation demo
    print("\n\nConnection Potential Score transformation (v8d):")
    print(f"{'Raw Prob':>10} {'Score (0-100)':>15}")
    print("-" * 28)
    demo = seed_results[0]["score_transform_demo"]
    for prob, score in sorted(demo.items()):
        print(f"{prob:>10.2f} {score:>15}")

    # ── Save model and metadata ────────────────────────────────────
    model_path = os.path.join(MODEL_ENGINEERING_DIR, f"logit_model_{LOGIT_MODEL_VERSION}.joblib")
    best_model.save(model_path)
    print(f"\nSaved model to {model_path}")

    # Extract coefficients for metadata
    coef_dict = {}
    if best_model.coef_df is not None:
        for _, row in best_model.coef_df.iterrows():
            coef_dict[row["feature"]] = round(row["coef"], 6)

    # Non-zero features count
    n_active = sum(1 for v in coef_dict.values() if abs(v) > 1e-6)

    metadata = {
        "model_version": LOGIT_MODEL_VERSION,
        "experiment": "v8_exploration_friendly",
        "hypothesis": (
            "Relaxed regularization (C=0.01-1.0) reactivates geometry and popularity features. "
            "Genre similarity features add cross-genre signal. Lowered threshold (0.35) surfaces "
            "potential connections for exploration UX. Score transformation maps to intuitive 0-100."
        ),
        "n2v_params": {
            "dim": 128, "p": 1.0, "q": 0.5,
            "epochs": 1, "walk_length": 20, "num_walks": 20,
            "window": 10, "workers": 2,
        },
        "features": features,
        "n_features": len(features),
        "n_active_features": n_active,
        "threshold": threshold,
        "pu_method": "elkanoto",
        "training_params": {
            "C_range": C_values,
            "best_C": seed_results[0]["best_C"],
            "best_l1_ratio": seed_results[0]["best_l1"],
            "max_iter": 3000,
            "hold_out_ratio": 0.2,
            "num_true_samples": num_true_samples,
            "neg_ratio": neg_ratio,
            "train_test_split": TEST_SIZE,
        },
        "mean_metrics": {k: round(v, 4) for k, v in mean_metrics.items()},
        "seed_results": seed_results,
        "threshold_sweep": sweep_df.to_dict(orient="records"),
        "coefficients": coef_dict,
        "score_transformation": {
            "method": "shifted_sigmoid",
            "midpoint": 0.3,
            "steepness": 6.0,
            "demo": seed_results[0]["score_transform_demo"],
        },
        "v6_baseline": V6_BASELINE,
        "v7_baseline": V7_BASELINE,
        "changes_vs_v7": [
            "v8a: Relaxed regularization (C=0.01-1.0 vs v7's C=0.001)",
            "v8b: Added 7 rosamerica genre similarity features",
            "v8c: Lowered threshold from 0.75 to 0.35",
            "v8d: Added connection_potential_score (0-100 scale)",
        ],
    }

    meta_path = os.path.join(MODEL_ENGINEERING_DIR, "metadata", f"logit_model_{LOGIT_MODEL_VERSION}.json")
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2, default=str)
    print(f"Saved metadata to {meta_path}")

    # Print classification report for seed=42
    print("\n\nClassification Report (seed=42, threshold={}):\n".format(threshold))
    y_pred = best_model.predict(best_X_test)
    print(classification_report(best_y_test, y_pred, target_names=["No Link", "Link"]))

    if best_model.coef_df is not None:
        print("\nFeature coefficients (sorted by magnitude):")
        print(best_model.coef_df.to_string(index=False))

    print("\n" + "=" * 70)
    print("v8 training complete.")
    print("=" * 70)


if __name__ == "__main__":
    main()
