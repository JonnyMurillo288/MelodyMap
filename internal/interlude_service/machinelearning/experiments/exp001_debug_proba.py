"""
Debug: Inspect the v5 model's predict_proba output distribution
to understand the PU classifier's probability semantics.
"""
import sys
import os
import numpy as np
import pandas as pd
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from sklearn.model_selection import train_test_split
from config.config import RANDOM_STATE, TEST_SIZE, MODEL_ENGINEERING_DIR
from models.link_predictor import LinkPredictor
from features.pipeline_links import build_link_prediction_features

NUM_TRUE_SAMPLES = 10_000
NEG_RATIO = 0.15
SEED = RANDOM_STATE
MODEL_PATH = os.path.join(MODEL_ENGINEERING_DIR, "logit_model_v5.joblib")

print("Building dataset...")
df = build_link_prediction_features(
    num_true_samples=NUM_TRUE_SAMPLES,
    neg_ratio=NEG_RATIO,
    random_state=SEED,
    save=False,
)

model = LinkPredictor.load(MODEL_PATH)
features = list(model.feature_names)

X = df[features].values
y = df["label"].values

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=TEST_SIZE, random_state=SEED, stratify=y,
)

# Get raw probabilities
y_prob = model.predict_proba(X_test)

print(f"\ny_prob shape: {y_prob.shape}")
print(f"y_prob dtype: {y_prob.dtype}")
print(f"y_prob min: {y_prob.min():.6f}")
print(f"y_prob max: {y_prob.max():.6f}")
print(f"y_prob mean: {y_prob.mean():.6f}")
print(f"y_prob median: {np.median(y_prob):.6f}")

# Distribution by class
link_mask = y_test == 1
nolink_mask = y_test == 0

print(f"\nFor LINK samples (y=1, n={link_mask.sum()}):")
print(f"  prob min:    {y_prob[link_mask].min():.6f}")
print(f"  prob max:    {y_prob[link_mask].max():.6f}")
print(f"  prob mean:   {y_prob[link_mask].mean():.6f}")
print(f"  prob median: {np.median(y_prob[link_mask]):.6f}")

print(f"\nFor NO-LINK samples (y=0, n={nolink_mask.sum()}):")
print(f"  prob min:    {y_prob[nolink_mask].min():.6f}")
print(f"  prob max:    {y_prob[nolink_mask].max():.6f}")
print(f"  prob mean:   {y_prob[nolink_mask].mean():.6f}")
print(f"  prob median: {np.median(y_prob[nolink_mask]):.6f}")

# Percentile distribution
print("\nPercentiles (all samples):")
for p in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
    print(f"  {p}th: {np.percentile(y_prob, p):.6f}")

# How many above various thresholds
print("\nFraction above threshold:")
for t in [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]:
    above = (y_prob >= t).sum()
    link_above = (y_prob[link_mask] >= t).sum()
    nolink_above = (y_prob[nolink_mask] >= t).sum()
    print(f"  t={t:.2f}: {above}/{len(y_prob)} total, "
          f"{link_above}/{link_mask.sum()} links, "
          f"{nolink_above}/{nolink_mask.sum()} nolinks")

# Also check raw model output before clipping
print("\n--- Checking raw model predict_proba ---")
best_pipeline = model.model.best_estimator_
raw = best_pipeline.predict_proba(X_test[:5])
print(f"Raw predict_proba shape: {raw.shape}")
print(f"Raw predict_proba sample:\n{raw[:5]}")

# Check what predict() returns
raw_pred = best_pipeline.predict(X_test[:10])
print(f"\nRaw predict sample: {raw_pred[:10]}")
print(f"y_test sample:      {y_test[:10]}")
