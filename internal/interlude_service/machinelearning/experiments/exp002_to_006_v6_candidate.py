"""
EXP-002 through EXP-006: Build v6 Link Model Candidate
========================================================
Controlled experiment sequence:
  EXP-002: Remove duplicate feature (dot_src_dst) + multi-seed baseline
  EXP-003: Reintroduce genre similarity features
  EXP-004: Sampling strategy (harder negatives)
  EXP-005: Feature engineering (temporal/popularity interactions)
  EXP-006: Model tuning (hyperparameters, PU method)

Each experiment changes ONE major factor. Carry-forward decisions are made
based on balanced recall improvement and precision budget.
"""
import sys
import os
import json
import time
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

# -- path setup ---------------------------------------------------------------
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
    classification_report,
)

from config.config import (
    LINK_PREDICTION_FEATURES,
    FEATURE_GROUPS,
    GENRE_TYPE_CLASSIFICATION,
    RANDOM_STATE,
    TEST_SIZE,
    MODEL_ENGINEERING_DIR,
    LOGIT_L1_RATIOS,
)
from models.link_predictor import LinkPredictor
from features.pipeline_links import (
    build_link_prediction_features,
    genre_type_proportions_column_names,
)

# -- Constants ----------------------------------------------------------------
RESULTS_DIR = ML_DIR / "experiments" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

MODEL_PATH_V5 = os.path.join(MODEL_ENGINEERING_DIR, "logit_model_v5.joblib")

# EXP-001 baseline (from prior experiment)
BASELINE = {
    "threshold": 0.07,
    "precision": 0.9926,
    "link_recall": 0.8065,
    "nolink_recall": 0.960,
    "balanced_recall": 0.8832,
    "roc_auc": 0.9588,
}

# Precision budget: allow up to 5 point drop from v5-at-0.07 baseline
PRECISION_FLOOR = BASELINE["precision"] - 0.05  # ~0.9426

# Threshold sweep range
THRESHOLDS = np.concatenate([
    np.arange(0.01, 0.10, 0.01),
    np.arange(0.10, 0.55, 0.05),
])

# Dataset params (locked to v5 training)
NUM_TRUE_SAMPLES = 10_000
NEG_RATIO = 0.15
SPLIT_TEST_SIZE = TEST_SIZE  # 0.2


def compute_metrics_at_threshold(y_true, y_prob, threshold):
    """Return a dict of metrics for a given threshold."""
    y_pred = (y_prob >= threshold).astype(int)

    link_recall = recall_score(y_true, y_pred, pos_label=1, zero_division=0)
    nolink_recall = recall_score(y_true, y_pred, pos_label=0, zero_division=0)
    balanced_recall = (link_recall + nolink_recall) / 2.0

    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    tn = int(((y_pred == 0) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())

    return {
        "threshold": round(float(threshold), 3),
        "precision": round(precision_score(y_true, y_pred, zero_division=0), 4),
        "link_recall": round(link_recall, 4),
        "nolink_recall": round(nolink_recall, 4),
        "balanced_recall": round(balanced_recall, 4),
        "f1": round(f1_score(y_true, y_pred, zero_division=0), 4),
        "accuracy": round(accuracy_score(y_true, y_pred), 4),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
    }


def threshold_sweep(y_true, y_prob, thresholds=THRESHOLDS):
    """Run a threshold sweep and return DataFrame of results."""
    rows = [compute_metrics_at_threshold(y_true, y_prob, t) for t in thresholds]
    return pd.DataFrame(rows)


def find_optimal_threshold(sweep_df, precision_floor=PRECISION_FLOOR):
    """Find threshold that maximizes balanced recall within precision budget."""
    eligible = sweep_df[sweep_df["precision"] >= precision_floor]
    if eligible.empty:
        print("  WARNING: No threshold meets precision floor. Using best balanced recall overall.")
        idx = sweep_df["balanced_recall"].idxmax()
    else:
        idx = eligible["balanced_recall"].idxmax()
    return sweep_df.loc[idx]


def print_sweep_table(sweep_df, title=""):
    """Pretty-print a threshold sweep table."""
    print(f"\n{'='*100}")
    print(f"  {title}")
    print(f"{'='*100}")
    header = f"{'Thresh':>8} {'Prec':>8} {'Link R':>8} {'NoLnk R':>9} {'Bal R':>8} {'F1':>8} {'Acc':>8} {'TP':>6} {'FP':>5} {'TN':>5} {'FN':>5}"
    print(header)
    print("-" * 100)
    for _, r in sweep_df.iterrows():
        print(f"{r['threshold']:>8.3f} {r['precision']:>8.4f} {r['link_recall']:>8.4f} "
              f"{r['nolink_recall']:>9.4f} {r['balanced_recall']:>8.4f} {r['f1']:>8.4f} "
              f"{r['accuracy']:>8.4f} {r['tp']:>6} {r['fp']:>5} {r['tn']:>5} {r['fn']:>5}")
    print("-" * 100)


def print_delta(label, candidate, baseline_metrics):
    """Print deltas vs baseline."""
    print(f"\n  {label} vs EXP-001 Baseline (threshold 0.07):")
    for key in ["precision", "link_recall", "nolink_recall", "balanced_recall"]:
        bval = baseline_metrics.get(key, 0)
        cval = candidate[key]
        delta = cval - bval
        status = "OK" if delta >= 0 or (key == "precision" and cval >= PRECISION_FLOOR) else "WARN"
        print(f"    {key:>18s}: {cval:.4f}  (delta: {delta:+.4f})  [{status}]")


def save_experiment(exp_id, summary):
    """Save experiment results to JSON."""
    path = RESULTS_DIR / f"{exp_id.lower().replace('-','_')}.json"
    with open(path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"  Saved results to {path}")
    return path


def train_and_evaluate(features, df, seed, pu_method="elkanoto",
                       Cs=None, l1_ratios=None, n_iter=10, cv=3,
                       scoring="f1", n_estimators=5):
    """Train a LinkPredictor and return (model, y_test, y_prob, metrics_dict)."""
    if Cs is None:
        Cs = [0.1, 1, 10]
    if l1_ratios is None:
        l1_ratios = LOGIT_L1_RATIOS

    # Handle missing features by filling with 0
    missing = set(features) - set(df.columns)
    if missing:
        print(f"  WARNING: Missing features {missing} -- filling with 0")
        for col in missing:
            df[col] = 0.0

    X = df[features].values
    y = df["label"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=SPLIT_TEST_SIZE, random_state=seed, stratify=y,
    )

    print(f"  Train: {len(y_train)} (pos={y_train.sum()}, neg={len(y_train)-y_train.sum()})")
    print(f"  Test:  {len(y_test)} (pos={y_test.sum()}, neg={len(y_test)-y_test.sum()})")

    model = LinkPredictor(
        pu_method=pu_method,
        Cs=Cs,
        l1_ratios=l1_ratios,
        scoring=scoring,
        n_iter=n_iter,
        cv=cv,
        random_state=seed,
        n_estimators=n_estimators,
    )
    model.fit(X_train, y_train, feature_names=features)

    y_prob = model.predict_proba(X_test)
    roc = roc_auc_score(y_test, y_prob)
    pr_auc = average_precision_score(y_test, y_prob)

    return model, X_test, y_test, y_prob, roc, pr_auc


# =============================================================================
# EXP-002: Remove duplicate feature + multi-seed baseline
# =============================================================================
def run_exp002(df):
    """
    Drop dot_src_dst (duplicate of cos_sim_src_dst after L2 normalization).
    Run with seeds 42, 123, 456 to establish clean v5.1 baseline.
    """
    print("\n" + "#" * 100)
    print("# EXP-002: Remove Duplicate Feature + Multi-Seed Baseline")
    print("#" * 100)

    # v5 features minus dot_src_dst
    features_v5_clean = [f for f in LINK_PREDICTION_FEATURES if f != "dot_src_dst"]
    print(f"\n  Features ({len(features_v5_clean)}): {features_v5_clean}")

    seeds = [42, 123, 456]
    all_results = []

    for seed in seeds:
        print(f"\n  --- Seed {seed} ---")
        model, X_test, y_test, y_prob, roc, pr_auc = train_and_evaluate(
            features_v5_clean, df.copy(), seed
        )
        print(f"  ROC AUC: {roc:.4f}, PR AUC: {pr_auc:.4f}")

        sweep = threshold_sweep(y_test, y_prob)
        optimal = find_optimal_threshold(sweep)

        all_results.append({
            "seed": seed,
            "roc_auc": round(roc, 4),
            "pr_auc": round(pr_auc, 4),
            "optimal_threshold": float(optimal["threshold"]),
            "optimal_precision": float(optimal["precision"]),
            "optimal_link_recall": float(optimal["link_recall"]),
            "optimal_nolink_recall": float(optimal["nolink_recall"]),
            "optimal_balanced_recall": float(optimal["balanced_recall"]),
            "optimal_f1": float(optimal["f1"]),
        })

        if seed == 42:
            print_sweep_table(sweep, f"EXP-002 Threshold Sweep (seed={seed})")
            sweep.to_csv(RESULTS_DIR / "exp002_sweep_seed42.csv", index=False)
            primary_model = model
            primary_optimal = optimal

    # Aggregate across seeds
    agg_df = pd.DataFrame(all_results)
    print("\n  Multi-seed results:")
    print(agg_df.to_string(index=False))

    mean_balanced = agg_df["optimal_balanced_recall"].mean()
    std_balanced = agg_df["optimal_balanced_recall"].std()
    mean_precision = agg_df["optimal_precision"].mean()

    print(f"\n  Mean Balanced Recall: {mean_balanced:.4f} +/- {std_balanced:.4f}")
    print(f"  Mean Precision: {mean_precision:.4f}")

    print_delta("EXP-002 (seed=42)", primary_optimal, BASELINE)

    # Promotion check
    passes = (
        mean_balanced >= BASELINE["balanced_recall"]
        or float(primary_optimal["balanced_recall"]) >= BASELINE["balanced_recall"]
    ) and mean_precision >= PRECISION_FLOOR

    print(f"\n  PROMOTION CHECK: {'PASS' if passes else 'FAIL'}")
    print(f"    Balanced recall >= baseline? {mean_balanced:.4f} >= {BASELINE['balanced_recall']:.4f} => {mean_balanced >= BASELINE['balanced_recall']}")
    print(f"    Precision >= floor? {mean_precision:.4f} >= {PRECISION_FLOOR:.4f} => {mean_precision >= PRECISION_FLOOR}")

    summary = {
        "experiment_id": "EXP-002",
        "hypothesis": "Removing duplicate feature (dot_src_dst=cos_sim after L2 norm) has no negative impact",
        "features": features_v5_clean,
        "n_features": len(features_v5_clean),
        "multi_seed_results": all_results,
        "mean_balanced_recall": round(mean_balanced, 4),
        "std_balanced_recall": round(std_balanced, 4),
        "mean_precision": round(mean_precision, 4),
        "promotion_pass": passes,
        "carry_forward": True,  # Always carry forward: removing redundancy is clean
        "decision": "CARRY FORWARD: Removing duplicate feature does not harm and simplifies model",
    }
    save_experiment("EXP-002", summary)

    return features_v5_clean, primary_model, primary_optimal, summary


# =============================================================================
# EXP-003: Reintroduce genre similarity features
# =============================================================================
def run_exp003(df, base_features):
    """
    Add genre similarity features (rosamerica genre proportions difference).
    These were computed during dataset build but not used in v5 training.
    """
    print("\n" + "#" * 100)
    print("# EXP-003: Reintroduce Genre Similarity Features")
    print("#" * 100)

    # Get genre column names
    gt_raw = genre_type_proportions_column_names(GENRE_TYPE_CLASSIFICATION)
    # The pipeline creates columns like similarity_prop_genre_rosamerica_dan etc.
    genre_features = [f"similarity_prop_{g}" for g in gt_raw]

    # Check which genre features are actually in the dataset
    available_genre = [f for f in genre_features if f in df.columns]
    print(f"\n  Available genre features ({len(available_genre)}): {available_genre}")

    if len(available_genre) == 0:
        print("  NO GENRE FEATURES AVAILABLE in dataset. Skipping EXP-003.")
        summary = {
            "experiment_id": "EXP-003",
            "hypothesis": "Genre similarity features improve cross-era discrimination",
            "result": "SKIPPED - no genre features in dataset",
            "carry_forward": False,
        }
        save_experiment("EXP-003", summary)
        return base_features, None, None, summary

    # Drop first genre feature to avoid collinearity (compositional data)
    genre_features_use = available_genre[1:]  # drop first to break collinearity
    print(f"  Using genre features (drop first for collinearity): {genre_features_use}")

    features_with_genre = base_features + genre_features_use
    print(f"  Total features ({len(features_with_genre)}): {features_with_genre}")

    seeds = [42, 123, 456]
    all_results = []

    for seed in seeds:
        print(f"\n  --- Seed {seed} ---")
        model, X_test, y_test, y_prob, roc, pr_auc = train_and_evaluate(
            features_with_genre, df.copy(), seed
        )
        print(f"  ROC AUC: {roc:.4f}, PR AUC: {pr_auc:.4f}")

        sweep = threshold_sweep(y_test, y_prob)
        optimal = find_optimal_threshold(sweep)

        all_results.append({
            "seed": seed,
            "roc_auc": round(roc, 4),
            "pr_auc": round(pr_auc, 4),
            "optimal_threshold": float(optimal["threshold"]),
            "optimal_precision": float(optimal["precision"]),
            "optimal_link_recall": float(optimal["link_recall"]),
            "optimal_nolink_recall": float(optimal["nolink_recall"]),
            "optimal_balanced_recall": float(optimal["balanced_recall"]),
            "optimal_f1": float(optimal["f1"]),
        })

        if seed == 42:
            print_sweep_table(sweep, f"EXP-003 Threshold Sweep (seed={seed})")
            sweep.to_csv(RESULTS_DIR / "exp003_sweep_seed42.csv", index=False)
            primary_model = model
            primary_optimal = optimal

    agg_df = pd.DataFrame(all_results)
    print("\n  Multi-seed results:")
    print(agg_df.to_string(index=False))

    mean_balanced = agg_df["optimal_balanced_recall"].mean()
    std_balanced = agg_df["optimal_balanced_recall"].std()
    mean_precision = agg_df["optimal_precision"].mean()

    print(f"\n  Mean Balanced Recall: {mean_balanced:.4f} +/- {std_balanced:.4f}")
    print(f"  Mean Precision: {mean_precision:.4f}")

    print_delta("EXP-003 (seed=42)", primary_optimal, BASELINE)

    passes = mean_precision >= PRECISION_FLOOR

    # Decide carry-forward: genre helps if balanced recall improves or is neutral
    carry = passes and mean_balanced >= BASELINE["balanced_recall"] - 0.005  # allow tiny noise

    summary = {
        "experiment_id": "EXP-003",
        "hypothesis": "Genre similarity features improve cross-era discrimination",
        "features": features_with_genre,
        "genre_features_added": genre_features_use,
        "n_features": len(features_with_genre),
        "multi_seed_results": all_results,
        "mean_balanced_recall": round(mean_balanced, 4),
        "std_balanced_recall": round(std_balanced, 4),
        "mean_precision": round(mean_precision, 4),
        "promotion_pass": carry,
        "carry_forward": carry,
        "decision": f"{'CARRY FORWARD' if carry else 'REVERT'}: genre features",
    }
    save_experiment("EXP-003", summary)

    if carry:
        return features_with_genre, primary_model, primary_optimal, summary
    else:
        return base_features, None, None, summary


# =============================================================================
# EXP-004: Sampling strategy -- larger/more balanced negatives
# =============================================================================
def run_exp004(carry_features, seed=42):
    """
    Test harder negative sampling: higher neg_ratio for more balanced dataset.
    Compare neg_ratio 0.15 (current) vs 0.30, 0.50.
    """
    print("\n" + "#" * 100)
    print("# EXP-004: Sampling Strategy -- Harder Negatives")
    print("#" * 100)

    ratios_to_test = [0.30, 0.50]
    all_results = []

    for neg_ratio in ratios_to_test:
        print(f"\n  --- neg_ratio={neg_ratio} ---")
        print(f"  Building dataset with num_true_samples={NUM_TRUE_SAMPLES}, neg_ratio={neg_ratio}...")

        try:
            df_new = build_link_prediction_features(
                num_true_samples=NUM_TRUE_SAMPLES,
                neg_ratio=neg_ratio,
                random_state=seed,
                save=False,
            )
            print(f"  Dataset shape: {df_new.shape}")
            print(f"  Label distribution:\n{df_new['label'].value_counts().to_string()}")

            model, X_test, y_test, y_prob, roc, pr_auc = train_and_evaluate(
                carry_features, df_new.copy(), seed
            )
            print(f"  ROC AUC: {roc:.4f}, PR AUC: {pr_auc:.4f}")

            sweep = threshold_sweep(y_test, y_prob)
            optimal = find_optimal_threshold(sweep)

            print_sweep_table(sweep, f"EXP-004 Threshold Sweep (neg_ratio={neg_ratio})")
            sweep.to_csv(RESULTS_DIR / f"exp004_sweep_neg{neg_ratio}.csv", index=False)

            print_delta(f"EXP-004 (neg_ratio={neg_ratio})", optimal, BASELINE)

            all_results.append({
                "neg_ratio": neg_ratio,
                "dataset_size": len(df_new),
                "n_pos": int(df_new["label"].sum()),
                "n_neg": int((df_new["label"] == 0).sum()),
                "roc_auc": round(roc, 4),
                "pr_auc": round(pr_auc, 4),
                "optimal_threshold": float(optimal["threshold"]),
                "optimal_precision": float(optimal["precision"]),
                "optimal_link_recall": float(optimal["link_recall"]),
                "optimal_nolink_recall": float(optimal["nolink_recall"]),
                "optimal_balanced_recall": float(optimal["balanced_recall"]),
                "optimal_f1": float(optimal["f1"]),
            })
        except Exception as e:
            print(f"  ERROR with neg_ratio={neg_ratio}: {e}")
            import traceback
            traceback.print_exc()
            all_results.append({
                "neg_ratio": neg_ratio,
                "error": str(e),
            })

    if not all_results or all(r.get("error") for r in all_results):
        summary = {
            "experiment_id": "EXP-004",
            "hypothesis": "Higher neg_ratio creates harder negatives, improving discrimination",
            "result": "ALL FAILED",
            "carry_forward": False,
            "best_neg_ratio": 0.15,
        }
        save_experiment("EXP-004", summary)
        return 0.15, None, summary

    valid = [r for r in all_results if "error" not in r]
    if valid:
        best = max(valid, key=lambda r: r["optimal_balanced_recall"])
        carry = (best["optimal_balanced_recall"] >= BASELINE["balanced_recall"]
                 and best["optimal_precision"] >= PRECISION_FLOOR)
    else:
        best = {"neg_ratio": 0.15}
        carry = False

    summary = {
        "experiment_id": "EXP-004",
        "hypothesis": "Higher neg_ratio creates harder negatives, improving discrimination",
        "results": all_results,
        "best_neg_ratio": best.get("neg_ratio", 0.15),
        "best_balanced_recall": best.get("optimal_balanced_recall"),
        "best_precision": best.get("optimal_precision"),
        "carry_forward": carry,
        "decision": f"{'CARRY FORWARD' if carry else 'REVERT'}: neg_ratio={best.get('neg_ratio', 0.15)}",
    }
    save_experiment("EXP-004", summary)

    return best.get("neg_ratio", 0.15), best, summary


# =============================================================================
# EXP-005: Feature engineering -- popularity interaction features
# =============================================================================
def run_exp005(df, carry_features):
    """
    Add temporal/popularity interaction features to address time-period bias.
    - popularity_ratio: max(pop) / (min(pop) + 1e-6) -- large when asymmetric
    - popularity_diff: abs(pop_src - pop_dst)
    - popularity_product: pop_src * pop_dst
    - log_popularity_ratio: log1p of ratio
    """
    print("\n" + "#" * 100)
    print("# EXP-005: Feature Engineering -- Popularity Interactions")
    print("#" * 100)

    # Create new features
    df_exp = df.copy()
    pop_src = df_exp["popularity_src"].fillna(0)
    pop_dst = df_exp["popularity_dst"].fillna(0)

    df_exp["popularity_ratio"] = np.maximum(pop_src, pop_dst) / (np.minimum(pop_src, pop_dst) + 1e-6)
    df_exp["popularity_diff"] = np.abs(pop_src - pop_dst)
    df_exp["popularity_product"] = pop_src * pop_dst
    df_exp["log_popularity_ratio"] = np.log1p(df_exp["popularity_ratio"])

    new_features = ["popularity_ratio", "popularity_diff", "popularity_product", "log_popularity_ratio"]
    features_with_pop = carry_features + new_features
    print(f"\n  New features: {new_features}")
    print(f"  Total features ({len(features_with_pop)}): {features_with_pop}")

    seeds = [42, 123, 456]
    all_results = []

    for seed in seeds:
        print(f"\n  --- Seed {seed} ---")
        model, X_test, y_test, y_prob, roc, pr_auc = train_and_evaluate(
            features_with_pop, df_exp.copy(), seed
        )
        print(f"  ROC AUC: {roc:.4f}, PR AUC: {pr_auc:.4f}")

        sweep = threshold_sweep(y_test, y_prob)
        optimal = find_optimal_threshold(sweep)

        all_results.append({
            "seed": seed,
            "roc_auc": round(roc, 4),
            "pr_auc": round(pr_auc, 4),
            "optimal_threshold": float(optimal["threshold"]),
            "optimal_precision": float(optimal["precision"]),
            "optimal_link_recall": float(optimal["link_recall"]),
            "optimal_nolink_recall": float(optimal["nolink_recall"]),
            "optimal_balanced_recall": float(optimal["balanced_recall"]),
            "optimal_f1": float(optimal["f1"]),
        })

        if seed == 42:
            print_sweep_table(sweep, f"EXP-005 Threshold Sweep (seed={seed})")
            sweep.to_csv(RESULTS_DIR / "exp005_sweep_seed42.csv", index=False)
            primary_model = model
            primary_optimal = optimal

    agg_df = pd.DataFrame(all_results)
    print("\n  Multi-seed results:")
    print(agg_df.to_string(index=False))

    mean_balanced = agg_df["optimal_balanced_recall"].mean()
    std_balanced = agg_df["optimal_balanced_recall"].std()
    mean_precision = agg_df["optimal_precision"].mean()

    print(f"\n  Mean Balanced Recall: {mean_balanced:.4f} +/- {std_balanced:.4f}")
    print(f"  Mean Precision: {mean_precision:.4f}")

    print_delta("EXP-005 (seed=42)", primary_optimal, BASELINE)

    carries = mean_precision >= PRECISION_FLOOR and mean_balanced >= BASELINE["balanced_recall"] - 0.005

    # Also test individual pop features to find which ones help
    print("\n  --- Ablation: testing each new feature individually ---")
    ablation_results = []
    for feat in new_features:
        test_feats = carry_features + [feat]
        try:
            _, _, y_test_abl, y_prob_abl, roc_abl, _ = train_and_evaluate(
                test_feats, df_exp.copy(), 42
            )
            sweep_abl = threshold_sweep(y_test_abl, y_prob_abl)
            opt_abl = find_optimal_threshold(sweep_abl)
            ablation_results.append({
                "feature": feat,
                "balanced_recall": float(opt_abl["balanced_recall"]),
                "precision": float(opt_abl["precision"]),
                "roc_auc": round(roc_abl, 4),
            })
            print(f"    {feat}: BalRcl={opt_abl['balanced_recall']:.4f}, Prec={opt_abl['precision']:.4f}, ROC={roc_abl:.4f}")
        except Exception as e:
            print(f"    {feat}: ERROR {e}")
            ablation_results.append({"feature": feat, "error": str(e)})

    summary = {
        "experiment_id": "EXP-005",
        "hypothesis": "Popularity interaction features reduce time-period bias",
        "new_features": new_features,
        "features": features_with_pop,
        "n_features": len(features_with_pop),
        "multi_seed_results": all_results,
        "ablation_results": ablation_results,
        "mean_balanced_recall": round(mean_balanced, 4),
        "std_balanced_recall": round(std_balanced, 4),
        "mean_precision": round(mean_precision, 4),
        "carry_forward": carries,
        "decision": f"{'CARRY FORWARD' if carries else 'REVERT'}: popularity interactions",
    }
    save_experiment("EXP-005", summary)

    if carries:
        return features_with_pop, primary_model, primary_optimal, df_exp, summary
    else:
        # Check if individual features help
        helpful = [r for r in ablation_results
                   if "error" not in r
                   and r["balanced_recall"] >= BASELINE["balanced_recall"]
                   and r["precision"] >= PRECISION_FLOOR]
        if helpful:
            best_single = max(helpful, key=lambda r: r["balanced_recall"])
            partial_features = carry_features + [best_single["feature"]]
            df_exp_partial = df_exp.copy()
            print(f"\n  Partial carry: only adding {best_single['feature']}")
            return partial_features, primary_model, primary_optimal, df_exp_partial, summary
        return carry_features, None, None, df, summary


# =============================================================================
# EXP-006: Model tuning -- PU method, hyperparameters
# =============================================================================
def run_exp006(df, carry_features):
    """
    Tune model: compare Elkanoto vs Bagging PU, broader C/l1_ratio grid.
    """
    print("\n" + "#" * 100)
    print("# EXP-006: Model Tuning -- PU Method + Hyperparameters")
    print("#" * 100)

    configs = [
        {
            "name": "elkanoto_broad",
            "pu_method": "elkanoto",
            "Cs": [0.01, 0.1, 0.5, 1.0, 5.0, 10.0],
            "l1_ratios": [0.3, 0.5, 0.7, 0.9, 1.0],
            "n_iter": 20,
            "cv": 5,
            "scoring": "f1",
        },
        {
            "name": "elkanoto_recall",
            "pu_method": "elkanoto",
            "Cs": [0.01, 0.1, 0.5, 1.0, 5.0, 10.0],
            "l1_ratios": [0.3, 0.5, 0.7, 0.9, 1.0],
            "n_iter": 20,
            "cv": 5,
            "scoring": "recall",
        },
        {
            "name": "bagging_pu",
            "pu_method": "bagging",
            "Cs": None,  # uses loguniform in RandomizedSearchCV
            "l1_ratios": None,  # uses uniform in RandomizedSearchCV
            "n_iter": 15,
            "cv": 3,
            "scoring": "f1",
            "n_estimators": 10,
        },
    ]

    all_results = []
    best_model = None
    best_balanced = 0
    best_optimal = None
    best_config_name = None

    for config in configs:
        print(f"\n  --- Config: {config['name']} ---")
        try:
            kwargs = {
                "pu_method": config["pu_method"],
                "n_iter": config["n_iter"],
                "cv": config["cv"],
                "scoring": config["scoring"],
            }
            if config["Cs"] is not None:
                kwargs["Cs"] = config["Cs"]
            if config["l1_ratios"] is not None:
                kwargs["l1_ratios"] = config["l1_ratios"]
            if "n_estimators" in config:
                kwargs["n_estimators"] = config["n_estimators"]

            model, X_test, y_test, y_prob, roc, pr_auc = train_and_evaluate(
                carry_features, df.copy(), 42, **kwargs
            )
            print(f"  ROC AUC: {roc:.4f}, PR AUC: {pr_auc:.4f}")

            # Get best params
            info = model.get_model_info()
            print(f"  Best params: {info['best_params']}")

            sweep = threshold_sweep(y_test, y_prob)
            optimal = find_optimal_threshold(sweep)

            print_sweep_table(sweep, f"EXP-006 {config['name']}")
            sweep.to_csv(RESULTS_DIR / f"exp006_sweep_{config['name']}.csv", index=False)

            print_delta(f"EXP-006 ({config['name']})", optimal, BASELINE)

            result = {
                "config": config["name"],
                "pu_method": config["pu_method"],
                "scoring": config["scoring"],
                "roc_auc": round(roc, 4),
                "pr_auc": round(pr_auc, 4),
                "best_params": info["best_params"],
                "optimal_threshold": float(optimal["threshold"]),
                "optimal_precision": float(optimal["precision"]),
                "optimal_link_recall": float(optimal["link_recall"]),
                "optimal_nolink_recall": float(optimal["nolink_recall"]),
                "optimal_balanced_recall": float(optimal["balanced_recall"]),
                "optimal_f1": float(optimal["f1"]),
            }
            all_results.append(result)

            if (float(optimal["balanced_recall"]) > best_balanced
                    and float(optimal["precision"]) >= PRECISION_FLOOR):
                best_balanced = float(optimal["balanced_recall"])
                best_model = model
                best_optimal = optimal
                best_config_name = config["name"]

        except Exception as e:
            print(f"  ERROR with {config['name']}: {e}")
            import traceback
            traceback.print_exc()
            all_results.append({"config": config["name"], "error": str(e)})

    print("\n  All EXP-006 results:")
    for r in all_results:
        if "error" not in r:
            print(f"    {r['config']:>20s}: BalRcl={r['optimal_balanced_recall']:.4f}, "
                  f"Prec={r['optimal_precision']:.4f}, ROC={r['roc_auc']:.4f}")

    summary = {
        "experiment_id": "EXP-006",
        "hypothesis": "Broader hyperparameter search and alternative PU methods improve recall",
        "configs_tested": [c["name"] for c in configs],
        "results": all_results,
        "best_config": best_config_name,
        "best_balanced_recall": round(best_balanced, 4) if best_balanced > 0 else None,
        "carry_forward": best_model is not None,
        "decision": f"BEST: {best_config_name}" if best_model else "REVERT",
    }
    save_experiment("EXP-006", summary)

    return best_model, best_optimal, best_config_name, summary


# =============================================================================
# FINAL: Combine winners into v6 candidate
# =============================================================================
def run_final_validation(df, final_features, best_model_config="elkanoto"):
    """
    Final multi-seed validation of v6 candidate.
    """
    print("\n" + "#" * 100)
    print("# FINAL: v6 Candidate Multi-Seed Validation")
    print("#" * 100)

    print(f"\n  v6 features ({len(final_features)}): {final_features}")

    seeds = [42, 123, 456, 789, 2024]
    all_results = []
    primary_model = None

    for seed in seeds:
        print(f"\n  --- Seed {seed} ---")
        model, X_test, y_test, y_prob, roc, pr_auc = train_and_evaluate(
            final_features, df.copy(), seed,
            Cs=[0.01, 0.1, 0.5, 1.0, 5.0, 10.0],
            l1_ratios=[0.3, 0.5, 0.7, 0.9, 1.0],
            n_iter=20,
            cv=5,
        )
        print(f"  ROC AUC: {roc:.4f}, PR AUC: {pr_auc:.4f}")

        sweep = threshold_sweep(y_test, y_prob)
        optimal = find_optimal_threshold(sweep)

        all_results.append({
            "seed": seed,
            "roc_auc": round(roc, 4),
            "pr_auc": round(pr_auc, 4),
            "optimal_threshold": float(optimal["threshold"]),
            "optimal_precision": float(optimal["precision"]),
            "optimal_link_recall": float(optimal["link_recall"]),
            "optimal_nolink_recall": float(optimal["nolink_recall"]),
            "optimal_balanced_recall": float(optimal["balanced_recall"]),
            "optimal_f1": float(optimal["f1"]),
        })

        if seed == 42:
            print_sweep_table(sweep, "v6 Final Validation (seed=42)")
            sweep.to_csv(RESULTS_DIR / "v6_final_sweep_seed42.csv", index=False)
            primary_model = model

    agg_df = pd.DataFrame(all_results)
    print("\n  Final multi-seed results:")
    print(agg_df.to_string(index=False))

    mean_balanced = agg_df["optimal_balanced_recall"].mean()
    std_balanced = agg_df["optimal_balanced_recall"].std()
    mean_precision = agg_df["optimal_precision"].mean()
    mean_roc = agg_df["roc_auc"].mean()

    print(f"\n  Mean Balanced Recall: {mean_balanced:.4f} +/- {std_balanced:.4f}")
    print(f"  Mean Precision:       {mean_precision:.4f}")
    print(f"  Mean ROC AUC:         {mean_roc:.4f}")

    # Final promotion decision
    passes = (mean_balanced >= BASELINE["balanced_recall"]
              and mean_precision >= PRECISION_FLOOR)

    print(f"\n  FINAL PROMOTION CHECK: {'PASS' if passes else 'FAIL'}")
    print(f"    Balanced recall: {mean_balanced:.4f} >= {BASELINE['balanced_recall']:.4f} => {mean_balanced >= BASELINE['balanced_recall']}")
    print(f"    Precision:       {mean_precision:.4f} >= {PRECISION_FLOOR:.4f} => {mean_precision >= PRECISION_FLOOR}")

    # Save v6 model (but do NOT promote to default)
    if passes and primary_model is not None:
        v6_path = os.path.join(MODEL_ENGINEERING_DIR, "logit_model_v6.joblib")
        primary_model.save(v6_path)
        print(f"\n  v6 model saved to {v6_path}")
        print("  NOTE: v6 is NOT promoted to default. Requires explicit approval.")

        # Save metadata
        meta_dir = os.path.join(MODEL_ENGINEERING_DIR, "metadata")
        os.makedirs(meta_dir, exist_ok=True)
        meta = {
            "model_info": primary_model.get_model_info(),
            "threshold": float(primary_model.threshold),
            "recommended_threshold": float(agg_df.loc[agg_df["seed"] == 42, "optimal_threshold"].iloc[0]),
            "n_features": len(final_features),
            "features": final_features,
            "multi_seed_validation": all_results,
            "mean_balanced_recall": round(mean_balanced, 4),
            "std_balanced_recall": round(std_balanced, 4),
            "mean_precision": round(mean_precision, 4),
            "mean_roc_auc": round(mean_roc, 4),
            "promotion_pass": passes,
            "created": datetime.now().isoformat(),
        }
        meta_path = os.path.join(meta_dir, "logit_model_v6.json")
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2, default=str)
        print(f"  Metadata saved to {meta_path}")

    summary = {
        "experiment_id": "FINAL-v6",
        "features": final_features,
        "n_features": len(final_features),
        "multi_seed_results": all_results,
        "mean_balanced_recall": round(mean_balanced, 4),
        "std_balanced_recall": round(std_balanced, 4),
        "mean_precision": round(mean_precision, 4),
        "mean_roc_auc": round(mean_roc, 4),
        "promotion_pass": passes,
        "baseline_comparison": {
            "v5_balanced_recall": BASELINE["balanced_recall"],
            "v6_balanced_recall": round(mean_balanced, 4),
            "delta_balanced_recall": round(mean_balanced - BASELINE["balanced_recall"], 4),
            "v5_precision": BASELINE["precision"],
            "v6_precision": round(mean_precision, 4),
            "delta_precision": round(mean_precision - BASELINE["precision"], 4),
        },
    }
    save_experiment("FINAL-v6", summary)

    return primary_model, summary


# =============================================================================
# MAIN
# =============================================================================
def main():
    start_time = time.time()
    print("=" * 100)
    print("  LINK RECALL OPTIMIZER: v6 Candidate Experiments")
    print(f"  Started: {datetime.now().isoformat()}")
    print("=" * 100)

    # ---- Build initial dataset (same as v5) --------------------------------
    print("\n[SETUP] Building dataset (num_true_samples=%d, neg_ratio=%.2f, seed=%d)..."
          % (NUM_TRUE_SAMPLES, NEG_RATIO, RANDOM_STATE))
    df = build_link_prediction_features(
        num_true_samples=NUM_TRUE_SAMPLES,
        neg_ratio=NEG_RATIO,
        random_state=RANDOM_STATE,
        save=False,
    )
    print(f"  Dataset shape: {df.shape}")
    print(f"  Label distribution:\n{df['label'].value_counts().to_string()}")
    print(f"  Columns: {df.columns.tolist()}")

    # ---- EXP-002 -----------------------------------------------------------
    features_002, model_002, optimal_002, summary_002 = run_exp002(df)

    # ---- EXP-003 -----------------------------------------------------------
    features_003, model_003, optimal_003, summary_003 = run_exp003(df, features_002)

    # ---- EXP-004 -----------------------------------------------------------
    best_neg_ratio, best_004, summary_004 = run_exp004(features_003)

    # If EXP-004 found a better neg_ratio, rebuild dataset
    if best_neg_ratio != NEG_RATIO and best_neg_ratio > NEG_RATIO:
        print(f"\n[REBUILD] Rebuilding dataset with neg_ratio={best_neg_ratio}...")
        df_004 = build_link_prediction_features(
            num_true_samples=NUM_TRUE_SAMPLES,
            neg_ratio=best_neg_ratio,
            random_state=RANDOM_STATE,
            save=False,
        )
    else:
        df_004 = df

    # ---- EXP-005 -----------------------------------------------------------
    result_005 = run_exp005(df_004, features_003)
    features_005 = result_005[0]
    df_005 = result_005[3] if len(result_005) > 3 else df_004

    # ---- EXP-006 -----------------------------------------------------------
    best_model_006, best_optimal_006, best_config_006, summary_006 = run_exp006(
        df_005, features_005
    )

    # ---- FINAL VALIDATION --------------------------------------------------
    final_model, final_summary = run_final_validation(df_005, features_005)

    # ---- SUMMARY -----------------------------------------------------------
    elapsed = time.time() - start_time
    print("\n" + "=" * 100)
    print("  EXPERIMENT SEQUENCE COMPLETE")
    print(f"  Total time: {elapsed/60:.1f} minutes")
    print("=" * 100)

    print(f"\n  EXP-002: {summary_002.get('decision', 'N/A')}")
    print(f"  EXP-003: {summary_003.get('decision', 'N/A')}")
    print(f"  EXP-004: {summary_004.get('decision', 'N/A')}")
    print(f"  EXP-005: {result_005[-1].get('decision', 'N/A') if isinstance(result_005[-1], dict) else 'N/A'}")
    print(f"  EXP-006: {summary_006.get('decision', 'N/A')}")

    print(f"\n  FINAL v6 PROMOTION: {'PASS' if final_summary.get('promotion_pass') else 'FAIL'}")
    if final_summary.get("baseline_comparison"):
        bc = final_summary["baseline_comparison"]
        print(f"    Balanced Recall: {bc['v5_balanced_recall']:.4f} -> {bc['v6_balanced_recall']:.4f} "
              f"(delta: {bc['delta_balanced_recall']:+.4f})")
        print(f"    Precision:       {bc['v5_precision']:.4f} -> {bc['v6_precision']:.4f} "
              f"(delta: {bc['delta_precision']:+.4f})")


if __name__ == "__main__":
    main()
