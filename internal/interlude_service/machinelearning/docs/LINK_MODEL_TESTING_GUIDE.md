# Link Recall Improvement Testing Guide

Build a repeatable experiment loop for link prediction that improves balanced recall while allowing a moderate 2-5 point precision tradeoff, using existing pipeline entrypoints and schema contracts so new feature/model versions can be added without breaking training or inference.

## Objectives

- Improve balanced recall across Link and No Link classes.
- Keep precision degradation within 2-5 points.
- Keep each experiment loop within 30-120 minutes.
- Preserve training and inference contracts for safe deployment.

## Phase Plan

1. Phase 1 - Baseline lock and reproducibility
- Freeze one reproducible baseline run with current v5 settings.
- Record seed, dataset parameters, feature set, threshold, and metrics.
- Save baseline artifacts as anchors for all future comparisons.

2. Phase 2 - Data and feature contract validation
- Add a pre-train validation checklist for required columns, null rates, and label distribution.
- Enforce training drop pattern: label, src, dst.
- Ensure selected feature list is a strict subset of generated columns.

3. Phase 3 - Recall-focused evaluation layer
- Expand from single-threshold reporting to threshold sweeps.
- Evaluate thresholds from 0.20 to 0.70.
- Track class-specific recalls and choose operating points that satisfy recall and precision constraints.

4. Phase 4 - Controlled feature experiments
- Run ablations/additions in small batches, not all-at-once.
- Batch A: topology-only subsets vs current mixed set.
- Batch B: genre variants (difference, absolute difference, optional Aitchison).
- Batch C: temporal/popularity interaction features.
- Version feature names and counts per experiment.

5. Phase 5 - Sampling and labeling experiments
- Compare current random SQL negatives vs harder negatives.
- Test stratified negatives by popularity and degree bands.
- Keep dataset size bounded to stay in runtime budget.

6. Phase 6 - Model and search experiments
- Compare Elkanoto PU vs Bagging PU.
- Tune search spaces and use recall-aligned scoring (recall, F-beta where beta > 1, or custom balanced-recall scorer).
- Keep logistic base model first; defer high-complexity models until gains flatten.

7. Phase 7 - Calibration and threshold policy
- Check Brier score and probability calibration behavior.
- Select default threshold per model version based on sweep outcomes, not fixed 0.5.

8. Phase 8 - Promotion criteria and versioning
- Promote only if baseline is beaten on balanced recall and precision floor is respected.
- Save model artifact, metadata, threshold, feature list, and changelog entry.

## Model Testing Loop (Every New Version)

1. Define experiment
- Set experiment_id, hypothesis, feature set, sampling strategy, PU method, threshold grid, and expected risk.

2. Build dataset
- Run link feature build with fixed seed and explicit parameters.
- Record row counts and class distribution.

3. Validate schema
- Assert required columns exist.
- Assert no leakage columns are present in train features.
- Assert inference uses the same feature_names used at training.

4. Train candidate
- Train with explicit scoring objective and logged hyperparameter search space.

5. Evaluate at multiple thresholds
- Report ROC AUC, PR AUC, precision, recall, F1, link recall, no-link recall, balanced recall, and confusion matrix at each threshold.

6. Compare against baseline
- Compute deltas.
- Reject candidate if precision drop exceeds agreed budget.

7. Robustness check
- Re-run top candidates with at least 3 random seeds.
- Prefer candidates with stable median gains.

8. Inference contract test
- Run single-artist prediction path.
- Run full-link scoring path.
- Confirm no missing columns or shape mismatches.

9. Register model version
- Save model, metadata JSON, selected threshold, and exact feature names.
- Update version changelog.

10. Release gate
- Verify runtime, memory, and rollback path via model registry.

## Pipeline Files To Edit Safely

- internal/interlude_service/machinelearning/README.md
- internal/interlude_service/machinelearning/QUICKSTART.md
- internal/interlude_service/machinelearning/run_pipeline.py
- internal/interlude_service/machinelearning/features/pipeline_links.py
- internal/interlude_service/machinelearning/features/build_features.py
- internal/interlude_service/machinelearning/features/sampling.py
- internal/interlude_service/machinelearning/models/link_predictor.py
- internal/interlude_service/machinelearning/config/config.py
- internal/interlude_service/machinelearning/models/model_registry.py
- internal/interlude_service/feature_engineering/MODEL_DOCUMENTATION.md

## Verification Checklist

1. Baseline reproducibility
- Run identical config twice; metrics should be near-identical.

2. Schema contract
- Training CSV must include src, dst, label, plus all selected model features.

3. Threshold-sweep completeness
- Candidate report must include per-threshold class recalls and precision deltas vs baseline.

4. Seed stability
- Top candidate must improve median balanced recall across 3 seeds.

5. Inference compatibility
- predict_link_features_from_artist path must run with trained feature_names without column mismatch errors.

6. Registry compatibility
- New version must load through model_registry; previous version remains selectable for rollback.

## Current Decisions

- Optimize balanced recall across classes.
- Accept moderate precision reduction (2-5 points).
- Keep experiment loops inside 30-120 minutes.
- Include feature engineering, sampling strategy, thresholding, and PU/logit tuning.
- Exclude, for now, major architecture replacements (for example, GNN migration) and API contract changes.

## Next Iteration Priorities

1. Add lightweight experiment tracking
- Persist per-run params, threshold, features, metrics, and artifact paths.

2. Add temporal features early
- Existing docs indicate cross-era mismatches; temporal features should be first-class test candidates.

3. Add dual operating modes
- Define one recall-first threshold preset for discovery and one precision-first preset for stricter use cases.
