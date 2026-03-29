# Phase 2 Implementation Changelog

> **Date**: 2026-03-29
> **Branch**: claude_branch
> **Source Plan**: PHASE2_IMPLEMENTATION_STRATEGY.md / INTERLUDE_SERVICE_STRATEGY.md Section 8

---

## Overview

Phase 2 completes the remaining 3 items from "Immediate Next Steps" (items 4, 6, 7) and adds a cross-cutting model version consistency fix plus the daily trends feature for the Spotle go-to-market.

All existing models, legacy endpoints, and Phase 1 endpoints remain untouched. Nothing breaks.

---

## What Was Implemented

### P2-0: Model Version Consistency Fix (Prerequisite)

**Problem**: Phase 1 endpoints used the model registry for plug-and-play version selection, but the DB helper functions hardcoded `LOGIT_MODEL_ID = 5` regardless of which model was actually used. Similarly, `check_existing_synthetic_tracks()` returned tracks for any CVAE version, ignoring the `synthetic_track_model_versions` table.

**File**: `machinelearning/models/model_registry.py`

Added `LOGIT_VERSION_TO_ID` mapping:

```python
LOGIT_VERSION_TO_ID = {"v1": 1, "v2": 2, "v3": 3, "v5": 5}
```

**File modified**: `machinelearning/app.py`

| Function | Change |
|---|---|
| `save_predictions_to_db(preds, model_id=None)` | Added `model_id` parameter. Defaults to `LOGIT_MODEL_ID` for backward compat. |
| `check_prediction_connections(src, dst, model_id=None)` | Added `model_id` parameter. Filters by actual model version instead of always using default. |
| `get_prediction_connections_for_src(src_id, limit, model_id=None)` | Added `model_id` parameter. Same default behavior. |
| `check_existing_synthetic_tracks(src, dst, limit, cvae_version=None)` | Added `cvae_version` parameter. When provided, joins on `synthetic_track_model_versions` and filters by CVAE version. When `None`, returns any version (legacy behavior). |

**File modified**: `machinelearning/routers/v1.py`

All existing Phase 1 endpoints now thread the correct model_id/cvae_version from the registry through their DB calls:
- `predict/connection` — passes `model_id` to cache check, save, and probability lookup
- `predict/neighbors` — passes `model_id` to `get_prediction_connections_for_src` and `save_predictions_to_db`
- `generate/tracks` — passes `cvae_version` to `check_existing_synthetic_tracks`

Legacy `/ml/*` endpoints in `app.py` continue using the hardcoded defaults — no change.

---

### P2-1: What-If Scenario Endpoint (Strategy Item 4)

**File**: `machinelearning/routers/v1.py`

```
POST /api/v1/explore/what-if
```

**Input**: 2-10 artist identifiers + optional constraints (genre target, popularity range, mood target) + model version + track/similarity limits.

**4-layer DB-first flow** (same pattern as existing endpoints):

| Layer | Check | On miss |
|---|---|---|
| 1. `scenario_cache` | Full cached what-if result (7-day TTL) | Continue to layer 2 |
| 2. `prediction_connections` | Stored probability for this model_id | Run link predictor → `save_predictions_to_db(model_id)` |
| 3. `synthetic_tracks` | Existing tracks for this CVAE version | Run CVAE → saves to `synthetic_tracks` + `synthetic_tracks_high_level_features` + `synthetic_track_model_versions` |
| 4. Aitchison similarity | Always computed | Matches synthetic tracks to real recordings |

**Key behaviors**:
- All intermediate results (predictions, synthetic tracks) are saved to the **shared tables** the frontend reads from
- Full result is cached in `scenario_cache` with 7-day TTL
- Pairs are sorted (min, max) so (A, B) and (B, A) share the same cache key
- Uses standard response envelope with latency and model version metadata

**Schemas added**: `WhatIfScenario`, `WhatIfRequest`, `WhatIfPairResult`, `WhatIfData`

---

### P2-2: Daily Trends Endpoint + Scheduler (Go-to-Market)

**File**: `machinelearning/routers/v1.py`

#### Read endpoint

```
GET /api/v1/trends/daily?date=2026-03-29&genre=rock&limit=5
```

Simple read from the `daily_predictions` table. Returns pre-computed featured connections with artist names, probabilities, genres, and synthetic track IDs.

**Schemas added**: `FeaturedConnection`, `DailyTrendsData`

#### Internal populate endpoint

```
POST /api/v1/internal/populate-daily
```

- Auth: `X-Internal-Secret` only (Go scheduler calls this)
- For each of 12 genres: gets top 50 artists, samples 5 random pairs, runs the full DB-first predict+generate pipeline
- All predictions and synthetic tracks are saved to the **shared tables** (not just `daily_predictions`)
- Returns `{ "rows_inserted": int, "genres_processed": int }`

**File modified**: `main/daily_scheduler.go`

Added `triggerV1PopulateDaily()` function that calls `POST /api/v1/internal/populate-daily` with the `X-Internal-Secret` header. Called in two places:
1. On startup (alongside existing `generateMissingPredictions()`)
2. At 12:00 PM EST daily tick (before existing `generateAllPredictions()`)

The existing Go-side prediction flow is preserved — `triggerV1PopulateDaily` runs first to populate the shared DB tables via the Python ML pipeline, then the existing Go-side generation runs as a fallback for any genres the Python endpoint didn't cover.

---

### P2-3: Dataset Export Endpoint (Strategy Item 6)

**File**: `machinelearning/routers/v1.py`

```
GET /api/v1/dataset/export?format=csv&genre=rock&min_probability=0.5&limit=10000
```

**Access control**:

| Tier | Access |
|---|---|
| Free | ❌ Blocked (unless admin) |
| Free + admin (`admin@interlude.local`) | ✅ Unlimited |
| Internal (`X-Internal-Secret`) | ✅ Unlimited |
| Researcher | ✅ Max 100k rows |
| Enterprise | ✅ Unlimited |

**Query**: Reads from the shared `prediction_connections` table with:
- Probability range filter
- Model version filter (via `LOGIT_VERSION_TO_ID`)
- Optional genre filter (via `artist_genre_proportions` join)
- LEFT JOIN on `synthetic_tracks` to include track count per pair

**Output formats**: CSV (`text/csv`) or Parquet (`application/octet-stream`) via streaming response.

**Audit**: Every export is logged to the `dataset_exports` table with user_id, filters, row_count, and format.

**Schema added**: `DatasetExportParams`

---

### P2-4: Stripe Billing Wiring (Strategy Item 7)

#### Python internal endpoint

**File**: `machinelearning/routers/v1.py`

```
POST /api/v1/internal/upgrade-tier
```

- Auth: `X-Internal-Secret` only
- Input: `{ "email": "user@example.com", "tier": "researcher" }`
- Updates `api_users.tier` and `api_users.rate_limit_per_hour`
- Tier → rate limit mapping: free=100, researcher=1000, enterprise=10000
- Returns confirmation with new tier and rate limit

**Schema added**: `UpgradeTierRequest`

#### Go webhook wiring

**File modified**: `main/daily_handlers.go`

Added `syncAPITier(email, tier)` function that calls the Python endpoint with `X-Internal-Secret`.

Wired into `stripeWebhookHandler`:
- On `checkout.session.completed`: calls `syncAPITier(customerEmail, "enterprise")` in a goroutine
- On `customer.subscription.deleted`: calls `syncAPITier("default_user", "free")` in a goroutine

Both calls are fire-and-forget (goroutine) so they don't block the webhook response to Stripe.

---

## What Was NOT Changed

- No existing model files (`.joblib`, `.pt`, `.pkl`) were modified
- No existing training code was modified
- No existing `/ml/*` or `/interlude/*` endpoint logic was changed
- No existing database tables were altered (all Phase 2 tables were created in Phase 1 migration)
- No existing Go frontend routes were changed
- No existing auth flow (Spotify OAuth, SDS tokens) was changed
- No Phase 1 endpoint behavior changed (only added version-aware params with backward-compatible defaults)

---

## File Inventory

### New Files
```
(none — all changes are additions to existing Phase 1/2 files)
```

### Modified Files
```
machinelearning/models/model_registry.py     — added LOGIT_VERSION_TO_ID mapping
machinelearning/app.py                       — added model_id/cvae_version params to 4 DB helpers
machinelearning/schemas/v1.py                — added 8 schema classes for Phase 2 endpoints
machinelearning/routers/v1.py                — version-aware existing endpoints + 5 new endpoints
main/daily_scheduler.go                      — added triggerV1PopulateDaily() + startup/daily calls
main/daily_handlers.go                       — added syncAPITier() + webhook wiring
```

---

## New Endpoints Summary

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/api/v1/explore/what-if` | POST | API key | "What if X and Y collaborated?" scenario explorer |
| `/api/v1/trends/daily` | GET | API key | Pre-computed daily featured predictions |
| `/api/v1/dataset/export` | GET | API key (tier-gated) | CSV/Parquet download of predictions |
| `/api/v1/internal/populate-daily` | POST | Internal secret | Scheduler populates daily predictions |
| `/api/v1/internal/upgrade-tier` | POST | Internal secret | Stripe webhook syncs user tier |

---

## Quickstart

```bash
# ---------------------------------------------------------------
# Prerequisites: Phase 1 must be complete (migration run, .env.docker set)
# ---------------------------------------------------------------

# 1. No new migration needed — Phase 2 tables were created in Phase 1
#    (scenario_cache, daily_predictions, dataset_exports already exist)

# 2. Build and start
docker compose up --build

# 3. Verify health (should show Phase 1 + Phase 2 endpoints)
curl http://localhost:8002/api/v1/health

# 4. Register an API key (if you don't have one from Phase 1)
curl -X POST http://localhost:8002/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com"}'

# ---------------------------------------------------------------
# Test What-If endpoint
# ---------------------------------------------------------------
curl -X POST http://localhost:8002/api/v1/explore/what-if \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "artists": ["Radiohead", "Bjork"],
    "num_tracks": 3,
    "num_similar": 3
  }'

# With constraints:
curl -X POST http://localhost:8002/api/v1/explore/what-if \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "artists": ["Kendrick Lamar", "Tame Impala", "FKA twigs"],
    "scenario": {"genre_target": "electronic", "mood_target": "aggressive"},
    "num_tracks": 5,
    "num_similar": 5
  }'

# ---------------------------------------------------------------
# Test Daily Trends endpoint
# ---------------------------------------------------------------
# The scheduler auto-populates on startup. Check today's predictions:
curl "http://localhost:8002/api/v1/trends/daily" \
  -H "X-API-Key: YOUR_KEY"

# Filter by genre:
curl "http://localhost:8002/api/v1/trends/daily?genre=rock&limit=3" \
  -H "X-API-Key: YOUR_KEY"

# Manually trigger population (admin/internal):
curl -X POST http://localhost:8002/api/v1/internal/populate-daily \
  -H "X-Internal-Secret: YOUR_INTERNAL_SECRET"

# ---------------------------------------------------------------
# Test Dataset Export endpoint
# ---------------------------------------------------------------
# CSV export (admin key — the seeded interlude-test-key-do-not-share-2026):
curl "http://localhost:8002/api/v1/dataset/export?format=csv&min_probability=0.5&limit=100" \
  -H "X-API-Key: interlude-test-key-do-not-share-2026" \
  -o predictions.csv

# Parquet export:
curl "http://localhost:8002/api/v1/dataset/export?format=parquet&genre=rock" \
  -H "X-API-Key: interlude-test-key-do-not-share-2026" \
  -o predictions.parquet

# Free-tier user will get 403:
curl "http://localhost:8002/api/v1/dataset/export" \
  -H "X-API-Key: FREE_TIER_KEY"
# → {"detail": "Export requires Researcher tier or above..."}

# ---------------------------------------------------------------
# Test Stripe tier sync (simulated)
# ---------------------------------------------------------------
# Manually upgrade a user's API tier:
curl -X POST http://localhost:8002/api/v1/internal/upgrade-tier \
  -H "X-Internal-Secret: YOUR_INTERNAL_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "tier": "researcher"}'

# ---------------------------------------------------------------
# Browse API docs (includes all Phase 2 endpoints)
# ---------------------------------------------------------------
open http://localhost:8002/docs

# ---------------------------------------------------------------
# Check metrics (includes new scenario/export counters)
# ---------------------------------------------------------------
curl http://localhost:8002/metrics
```
