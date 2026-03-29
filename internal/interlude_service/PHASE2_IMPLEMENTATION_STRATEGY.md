# Phase 2 Implementation Strategy

> **Date**: 2026-03-29
> **Branch**: claude_branch
> **Depends on**: Phase 1 (complete — see PHASE1_CHANGELOG.md)

---

## Phase 1 Assessment

Phase 1 is fully implemented with no stubs or placeholders. Here's the coverage against the 8 Immediate Next Steps from INTERLUDE_SERVICE_STRATEGY.md:

| # | Item | Phase 1 Status |
|---|------|---------------|
| 1 | Security: Remove hardcoded credentials | ✅ Done — config.py uses env vars, `.env.example` created |
| 2 | API auth middleware + rate limiting | ✅ Done — `middleware/auth.py`, 3-tier rate limits, usage logging |
| 3 | Artist profile endpoint | ✅ Done — `GET /api/v1/artist/{id}/profile` fully implemented |
| 4 | **What-if endpoint** | ❌ Not built |
| 5 | Batch endpoint | ✅ Done — `POST /api/v1/predict/batch` (up to 1000 pairs) |
| 6 | **Export endpoint** | ❌ Not built |
| 7 | **Stripe integration** | ⚠️ Partial — Go side has `stripeCreateCheckoutHandler` + `stripeWebhookHandler`, but no Python-side tier enforcement wiring |
| 8 | Monitoring | ✅ Done — Prometheus metrics, `/metrics` endpoint, 3 metric categories |

**Additionally delivered in Phase 1 (beyond the 8 steps):**
- Model registry with per-request version switching
- A/B model comparison endpoint (`/predict/compare`)
- Standardized Pydantic v2 response envelope
- Caddy TLS reverse proxy
- Go → Python internal auth (`X-Internal-Secret`)
- DB migration for all Phase 2 tables (already created)

**Database tables already exist** from Phase 1 migration (`001_phase1_tables.sql`):
- `scenario_cache` — ready for what-if endpoint
- `daily_predictions` — ready for daily trends endpoint
- `dataset_exports` — ready for export audit trail
- `api_users`, `api_usage_log`, `prediction_feedback` — in use

---

## Phase 2 Scope

Phase 2 completes the remaining 3 items from Immediate Next Steps (4, 6, 7) plus the daily trends endpoint which is needed for the Spotle integration and the go-to-market "Daily Discovery" feature.

### Deliverables

| # | Deliverable | Strategy Section | Priority |
|---|-------------|-----------------|----------|
| **P2-1** | What-if scenario endpoint | 2.2 Tier 3 | High |
| **P2-2** | Daily trends endpoint + scheduler | 2.2 Tier 3 | High |
| **P2-3** | Dataset export endpoint | 2.2 Tier 3 | High |
| **P2-4** | Stripe billing wiring (Python ↔ Go) | 6.3 | Medium |

---

## P2-0: Model Version Consistency Fix (prerequisite)

Before building any new endpoints, the DB-first lookup and persist logic must be **model-version-aware**. Today there are two gaps:

### Gap 1: `prediction_connections` — save uses hardcoded model_id

`save_predictions_to_db()` always writes `model_id = LOGIT_MODEL_ID` (hardcoded to `5`), regardless of which model version was actually used. The v1 router calls `registry.get_logit(req.model_version)` to load e.g. v3, but the saved row still says `model_id=5`.

**Similarly**, `check_prediction_connections(src, dst)` filters by `model_id = LOGIT_MODEL_ID`, so it only finds rows saved by the default model. If a user ran a prediction with `model_version=v3`, a later lookup won't find it.

**Fix**:
- `save_predictions_to_db(preds, model_id)` — add `model_id` parameter, stop hardcoding
- `check_prediction_connections(src, dst, model_id)` — pass the actual model_id from the registry
- `get_prediction_connections_for_src(src_id, model_id, limit)` — same
- In the v1 router, the registry returns `(model, version_str)`. Map version string to model_id:
  ```python
  # model_registry.py — add version-to-id mapping
  LOGIT_VERSION_TO_ID = {"v1": 1, "v2": 2, "v3": 3, "v5": 5}
  ```

### Gap 2: `synthetic_tracks` — lookup ignores model version

`check_existing_synthetic_tracks(src, dst)` returns tracks for the pair regardless of which CVAE version generated them. But `generate_synthetic_tracks()` *does* write the version to `synthetic_track_model_versions`.

The lookup just never checks it. So if a user requests tracks with `cvae_v2` but `cvae_v1` tracks already exist, they get the v1 tracks silently.

**Fix**:
- `check_existing_synthetic_tracks(src, dst, cvae_version, limit)` — join on `synthetic_track_model_versions` and filter by version:
  ```sql
  SELECT st.track_id, shlf.prob
  FROM synthetic_tracks st
  JOIN synthetic_tracks_high_level_features shlf ON st.track_id = shlf.track_id
  JOIN synthetic_track_model_versions stmv ON st.track_id = stmv.track_id
  WHERE st.src_artist_id = %s AND st.dst_artist_id = %s
    AND stmv.model_name = 'cvae' AND stmv.version = %s
  ORDER BY shlf.prob DESC
  LIMIT %s;
  ```

### Impact on existing endpoints

These fixes also apply to the Phase 1 endpoints in `routers/v1.py`:
- `predict/connection` — pass `model_id` from registry to `save_predictions_to_db` and `check_prediction_connections`
- `predict/neighbors` — pass `model_id` to `get_prediction_connections_for_src`
- `generate/tracks` — pass `cvae_version` to `check_existing_synthetic_tracks`

The legacy `/ml/*` endpoints in `app.py` continue using `LOGIT_MODEL_ID` as before — no change to them.

### Files to modify

| File | Change |
|---|---|
| `app.py` | Add `model_id` param to `save_predictions_to_db`, `check_prediction_connections`, `get_prediction_connections_for_src`. Add `cvae_version` param to `check_existing_synthetic_tracks`. Keep defaults as `LOGIT_MODEL_ID`/`None` so legacy callers are unaffected. |
| `models/model_registry.py` | Add `LOGIT_VERSION_TO_ID` mapping dict |
| `routers/v1.py` | Thread model_id and cvae_version through all DB calls |

---

## P2-1: What-If Scenario Endpoint

### Endpoint

```
POST /api/v1/explore/what-if
```

### What it does

Takes 2+ artists and optional constraints (genre target, popularity range, mood target), then for each pair:
1. Runs the link predictor to get collaboration probability
2. Generates synthetic tracks via CVAE with constraint steering
3. Finds real tracks similar to the synthetic tracks via Aitchison distance
4. Caches the full result in `scenario_cache` (7-day TTL)

This is the key differentiator for non-technical users — "What would happen if X and Y collaborated?"

### Schema additions (`schemas/v1.py`)

```python
class WhatIfScenario(BaseModel):
    genre_target: str | None = None
    popularity_range: tuple[int, int] | None = None
    mood_target: str | None = None

class WhatIfRequest(BaseModel):
    artists: list[str]  # 2-10 artist identifiers (MBID, Spotify ID, or name)
    scenario: WhatIfScenario | None = None

class WhatIfPairResult(BaseModel):
    src_artist: str
    dst_artist: str
    probability: float
    synthetic_tracks: list[dict]  # CVAE output features
    similar_real_tracks: list[dict]  # Aitchison-matched real tracks

class WhatIfData(BaseModel):
    scenarios: list[WhatIfPairResult]
```

### Implementation logic (`routers/v1.py`)

This follows the same **DB-first pattern** used by the existing endpoints (`predict/connection`, `predict/neighbors`, `generate/tracks`). Every search checks the database for existing results before calling any models, and every model output is persisted back to the database so future lookups are instant.

```
1. Validate artists list (2-10 items)
2. Resolve all artist identifiers to internal IDs (reuse _resolve_artist helper)
3. Generate all unique pairs from the artist list
4. For each pair:

   ┌─────────────────────────────────────────────────────────┐
   │  LAYER 1: Check scenario_cache (full what-if result)    │
   │                                                         │
   │  Query scenario_cache by cache_key (hash of sorted      │
   │  pair + constraints). If found and not expired →        │
   │  return the full cached result immediately.             │
   │  Same pattern as check_prediction_connections().        │
   └────────────────────┬────────────────────────────────────┘
                        │ miss
   ┌────────────────────▼────────────────────────────────────┐
   │  LAYER 2: Check prediction_connections (link prob)      │
   │                                                         │
   │  Call check_prediction_connections(src, dst, model_id)  │
   │  with the model_id from the registry (P2-0 fix).      │
   │  If yes → use the stored probability, skip model call. │
   │  If no  → run link predictor (via registry), then      │
   │           save_predictions_to_db(pred_df, model_id)    │
   │           to persist with the correct model_id.         │
   └────────────────────┬────────────────────────────────────┘
                        │
   ┌────────────────────▼────────────────────────────────────┐
   │  LAYER 3: Check synthetic_tracks (CVAE output)          │
   │                                                         │
   │  Call check_existing_synthetic_tracks(src, dst,         │
   │    cvae_version) — filters via the                      │
   │  synthetic_track_model_versions join (P2-0 fix).        │
   │  If yes → use existing track IDs, skip CVAE.           │
   │  If no  → call generate_synthetic_tracks() which runs  │
   │           the CVAE and saves output to:                 │
   │           • synthetic_tracks (track_id, src, dst)       │
   │           • synthetic_tracks_high_level_features        │
   │           • synthetic_track_model_versions (version!)   │
   └────────────────────┬────────────────────────────────────┘
                        │
   ┌────────────────────▼────────────────────────────────────┐
   │  LAYER 4: Aitchison similarity (real track matching)    │
   │                                                         │
   │  Run TrackSimilarity on the synthetic track IDs.        │
   │  This is always computed (not cached), same as the      │
   │  existing /generate/playlist endpoint.                  │
   └────────────────────┬────────────────────────────────────┘
                        │
   ┌────────────────────▼────────────────────────────────────┐
   │  PERSIST: Save full what-if result to scenario_cache    │
   │                                                         │
   │  INSERT INTO scenario_cache (cache_key, result,         │
   │    expires_at) the complete JSON response for this pair │
   │  + constraints. TTL = 7 days.                           │
   └─────────────────────────────────────────────────────────┘

5. Return all pair results in standard envelope
```

**Key principle**: Every intermediate result (prediction probability, synthetic tracks) is saved to the same tables the frontend uses. This means:
- A what-if search via the API populates the same `prediction_connections` and `synthetic_tracks` tables
- The frontend's "Non-connected artists" table will show these results on the next page load
- The `/predict/connection` endpoint will return cached results for any pair previously explored via what-if
- No duplicate model calls — the DB is the single source of truth

### Cache key design

```python
import hashlib, json
def scenario_cache_key(src_id: int, dst_id: int, scenario: dict) -> str:
    pair = tuple(sorted([src_id, dst_id]))
    payload = json.dumps({"pair": pair, "scenario": scenario}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()
```

### Constraint steering

The CVAE conditioning vector C currently contains: `cos_sim, l2_dist, popularity_src, popularity_dst, mean_topk_cos, shared_neighbors`. Constraints modify C before generation:

| Constraint | How it modifies C |
|---|---|
| `genre_target` | Post-generation filter: regenerate until majority genre matches target, up to 5 attempts |
| `popularity_range` | Clamp `popularity_src` and `popularity_dst` in C to the given range before generation |
| `mood_target` | Post-generation filter: keep tracks where mood output matches target |

This is a "soft steering" approach — no CVAE retraining needed. Hard steering (retraining with constraint conditioning) is a Phase 3 model improvement.

### Files to modify/create

| File | Change |
|---|---|
| `schemas/v1.py` | Add `WhatIfScenario`, `WhatIfRequest`, `WhatIfPairResult`, `WhatIfData` |
| `routers/v1.py` | Add `POST /api/v1/explore/what-if` handler |

No new files needed. Uses existing `scenario_cache` table, and persists all intermediate results to `prediction_connections`, `synthetic_tracks`, and `synthetic_tracks_high_level_features` — the same tables the frontend reads from.

---

## P2-2: Daily Trends Endpoint + Scheduler

### Endpoint

```
GET /api/v1/trends/daily
```

### What it does

Returns pre-computed daily featured predictions. Data is populated by a scheduler that runs daily, not computed on request.

### Query parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `date` | `YYYY-MM-DD` | today | Which day's predictions to return |
| `genre` | `str` | all | Filter by genre |
| `limit` | `int` | 5 | Number of featured connections |

### Schema additions (`schemas/v1.py`)

```python
class FeaturedConnection(BaseModel):
    src_artist_name: str
    dst_artist_name: str
    probability: float
    genre: str
    synthetic_track_ids: list[int]

class DailyTrendsData(BaseModel):
    date: str
    featured_connections: list[FeaturedConnection]
```

### Implementation logic — endpoint (`routers/v1.py`)

```
1. Parse date param (default today), genre filter, limit
2. Query daily_predictions table:
   SELECT * FROM daily_predictions
   WHERE prediction_date = %s
   AND (genre = %s OR %s IS NULL)
   ORDER BY probability DESC
   LIMIT %s
3. Return in standard envelope
```

This endpoint is a simple read from a pre-populated table.

### Implementation logic — daily scheduler

The scheduler needs to populate `daily_predictions` each day. Two options:

**Option A (recommended): Python-side scheduler in FastAPI**

Add a background task using `apscheduler` or a simple startup coroutine that runs at midnight EST:

**Option A: Extend existing Go scheduler (recommended)**

`daily_scheduler.go` already has a `startDailyScheduler()` function that runs tasks on a ticker. Add a call to a new Python endpoint `POST /api/v1/internal/populate-daily` that does the computation. The Go side just triggers it.

**Recommendation**: Option A — keeps the scheduling in Go (where it already lives) and the ML logic in Python (where it belongs). The Go scheduler calls one Python endpoint.

### New internal endpoint

```
POST /api/v1/internal/populate-daily
```

- Auth: `X-Internal-Secret` only (not exposed to API users)
- Returns `{ "rows_inserted": int, "genres_processed": int }`

### Implementation logic — populate-daily (DB-first pattern)

The populate endpoint follows the same DB-first + persist pattern as every other endpoint. Each pair's results are saved to the **shared tables** so they're immediately available to the frontend and all other API endpoints.

```
For each genre:
  1. Get top 50 artists in this genre (from artist_genre_proportions)
  2. Sample 5 random pairs from those artists
  3. For each pair (src, dst):

     a. CHECK prediction_connections first (version-aware)
        → call check_prediction_connections(src, dst, model_id)
          where model_id comes from the registry (P2-0 fix)
        → if exists for this model version: use stored probability
        → if not: run link predictor via registry, then
          call save_predictions_to_db(pred_df, model_id)
          to persist to prediction_connections with correct model_id

     b. CHECK synthetic_tracks first (version-aware)
        → call check_existing_synthetic_tracks(src, dst, cvae_version)
          which joins on synthetic_track_model_versions (P2-0 fix)
        → if tracks exist for this CVAE version: use those track IDs
        → if not: call generate_synthetic_tracks()
          which persists to:
          • synthetic_tracks
          • synthetic_tracks_high_level_features
          • synthetic_track_model_versions (with version tag)

     c. INSERT INTO daily_predictions
        (prediction_date, genre, src_artist_id, src_artist_name,
         dst_artist_id, dst_artist_name, probability, synthetic_track_ids)

        This is the only daily-specific table write.
        The prediction + tracks are in the shared tables.
```

**Why this matters**: When a user sees the daily prediction on the frontend and clicks on a pair, the frontend's existing `check_prediction_connections()` call will find it immediately. The synthetic tracks are already in the same tables the "Saved Connections" panel queries. Zero extra work on the frontend side.

### Files to modify

| File | Change |
|---|---|
| `schemas/v1.py` | Add `FeaturedConnection`, `DailyTrendsData` |
| `routers/v1.py` | Add `GET /api/v1/trends/daily` + `POST /api/v1/internal/populate-daily` |
| `main/daily_scheduler.go` | Add call to `/api/v1/internal/populate-daily` in the daily tick |

---

## P2-3: Dataset Export Endpoint

### Endpoint

```
GET /api/v1/dataset/export
```

### What it does

Returns a downloadable file (CSV or Parquet) of prediction data filtered by the user's criteria. Tier-restricted — free users can only export if they have admin access (e.g. the seeded `admin@interlude.local` account).

| Tier | Access |
|---|---|
| Free | ❌ No export (unless admin) |
| Researcher | ✅ Monthly, max 100k rows |
| Enterprise | ✅ Daily, unlimited rows |

### Query parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `format` | `csv` or `parquet` | `csv` | Output format |
| `genre` | `str` | all | Filter predictions by genre |
| `min_probability` | `float` | 0.0 | Minimum prediction probability |
| `max_probability` | `float` | 1.0 | Maximum prediction probability |
| `limit` | `int` | 10000 | Max rows (capped by tier) |
| `model_version` | `str` | default | Filter by model version |

### Schema additions (`schemas/v1.py`)

```python
class DatasetExportParams(BaseModel):
    format: str = "csv"  # "csv" or "parquet"
    genre: str | None = None
    min_probability: float = 0.0
    max_probability: float = 1.0
    limit: int = 10000
    model_version: str | None = None
```

### Implementation logic (`routers/v1.py`)

This endpoint is a **read-only export from the shared database**. It queries the same `prediction_connections` and `synthetic_tracks` tables that the frontend, what-if, and daily endpoints all write to. Every search from any endpoint enriches the export dataset.

```
1. Check user tier and admin status:
   - Free + not admin → 403 "Export requires Researcher tier or above"
   - Free + admin → allow (unlimited, same as enterprise)
   - Researcher → cap limit at 100,000, check monthly quota
   - Enterprise → no limit

   Admin check: compare user email to a known admin list
   (e.g. email == 'admin@interlude.local' or a new `is_admin`
   boolean column on api_users). The seeded admin account from
   001_phase1_tables.sql already has tier='enterprise', but this
   also covers any free-tier account you flag as admin.

2. Query the shared prediction_connections table with filters:
   SELECT pc.src, a1.name as src_name, a1.gid as src_mbid,
          pc.dst, a2.name as dst_name, a2.gid as dst_mbid,
          pc.prob, pc.model_id
   FROM prediction_connections pc
   JOIN artist a1 ON a1.id = pc.src::int
   JOIN artist a2 ON a2.id = pc.dst::int
   WHERE pc.prob BETWEEN %s AND %s
   AND pc.model_id = %s  -- filter by model version (P2-0)
   AND (%s IS NULL OR EXISTS (
       SELECT 1 FROM artist_genre_proportions agp
       WHERE agp.artist_id = pc.src::int AND agp.genre = %s
   ))
   ORDER BY pc.prob DESC
   LIMIT %s

   Note: column names are src/dst/prob/model_id,
   matching the existing prediction_connections schema used by
   save_predictions_to_db() and check_prediction_connections().
   The model_version query param maps to model_id via
   LOGIT_VERSION_TO_ID (P2-0 fix). Default = current default model.

3. Optionally join synthetic track counts per pair:
   LEFT JOIN (
       SELECT src_artist_id, dst_artist_id, COUNT(*) as track_count
       FROM synthetic_tracks
       GROUP BY src_artist_id, dst_artist_id
   ) st ON st.src_artist_id = pc.src::int AND st.dst_artist_id = pc.dst::int

   This tells the consumer how many synthetic tracks are available for each pair.

4. Format as CSV (pandas to_csv) or Parquet (pandas to_parquet with pyarrow)
5. Log to dataset_exports table (user_id, filters, row_count, format)
6. Return as StreamingResponse with appropriate Content-Type and Content-Disposition headers
```

### Dependencies

- `pyarrow` — needed for Parquet export. Add to `requirements.txt`.

### Files to modify

| File | Change |
|---|---|
| `schemas/v1.py` | Add `DatasetExportParams` |
| `routers/v1.py` | Add `GET /api/v1/dataset/export` handler |
| `requirements.txt` | Add `pyarrow` |

---

## P2-4: Stripe Billing Wiring

### Current state

The Go side (`daily_handlers.go`) already has:
- `stripeCreateCheckoutHandler` — creates Stripe Checkout sessions
- `stripeWebhookHandler` — processes payment confirmation + tier upgrades
- Uses `STRIPE_SECRET_KEY` env var

The Python side (`middleware/auth.py`) already enforces tier-based rate limits by reading the `tier` column from `api_users`.

### What's missing

The Stripe flow in Go updates user tiers, but the Go service and Python service use **different user identity systems**:
- Go side: Spotify OAuth sessions (browser users)
- Python side: `api_users` table with API keys

We need to bridge these so that a Stripe payment by a browser user upgrades their API tier too.

### Implementation

```
Stripe Checkout Flow (existing, in Go):
  1. Browser user clicks "Upgrade" on /ml page
  2. Go creates Stripe Checkout session with user email as metadata
  3. User completes payment on Stripe
  4. Stripe webhook hits Go → stripeWebhookHandler

Additions needed:
  5. stripeWebhookHandler reads email from Stripe session metadata
  6. Go calls Python: POST /api/v1/internal/upgrade-tier
     Body: { "email": "user@example.com", "tier": "researcher" }
     Header: X-Internal-Secret
  7. Python updates api_users SET tier = %s WHERE email = %s
  8. Rate limits immediately reflect new tier (auth middleware reads from DB)
```

### New internal endpoint

```
POST /api/v1/internal/upgrade-tier
```

- Auth: `X-Internal-Secret` only
- Input: `{ "email": str, "tier": str }`
- Updates `api_users.tier` and `api_users.rate_limit_per_hour`
- Returns confirmation

### Files to modify

| File | Change |
|---|---|
| `routers/v1.py` | Add `POST /api/v1/internal/upgrade-tier` |
| `schemas/v1.py` | Add `UpgradeTierRequest` |
| `main/daily_handlers.go` | In `stripeWebhookHandler`, after tier update, call Python internal endpoint |

---

## Implementation Order

```
P2-0  Model version consistency fix    ← PREREQUISITE for all other work
  │
  ├── app.py: add model_id/cvae_version params to DB helpers
  ├── model_registry.py: add LOGIT_VERSION_TO_ID mapping
  └── routers/v1.py: thread version through existing endpoints
      (predict/connection, predict/neighbors, generate/tracks)

P2-1  What-if endpoint                 ← highest user-facing value
  │
  ├── schemas (WhatIf*)
  └── router handler + 4-layer DB-first logic with version filtering

P2-2  Daily trends                     ← needed for Spotle / go-to-market
  │
  ├── schemas (DailyTrends*)
  ├── read endpoint (simple DB query)
  └── internal populate endpoint + Go scheduler call

P2-3  Dataset export                   ← researcher/enterprise feature
  │
  ├── schemas (Export*)
  ├── router handler + streaming response (version-filtered)
  └── requirements.txt (pyarrow)

P2-4  Stripe wiring                    ← connects payment to tier enforcement
  │
  ├── internal upgrade-tier endpoint
  └── Go webhook handler update
```

**P2-0 must be done first** — it fixes the DB helpers that all other deliverables depend on. P2-1 through P2-4 are independent of each other and can be built in any order after P2-0.

---

## Files Changed Summary

### New files
None — all changes are additions to existing Phase 1 files.

### Modified files

| File | Changes |
|---|---|
| `machinelearning/app.py` | P2-0: Add `model_id` param to `save_predictions_to_db`, `check_prediction_connections`, `get_prediction_connections_for_src`. Add `cvae_version` param to `check_existing_synthetic_tracks`. Defaults preserve backward compat for legacy `/ml/*` callers. |
| `machinelearning/models/model_registry.py` | P2-0: Add `LOGIT_VERSION_TO_ID` mapping dict |
| `machinelearning/schemas/v1.py` | +6 schema classes (WhatIf*, DailyTrends*, Export*, UpgradeTier*) |
| `machinelearning/routers/v1.py` | P2-0: Thread model_id/cvae_version through existing endpoints. P2-1–4: +5 new endpoints (what-if, trends/daily, populate-daily, export, upgrade-tier) |
| `machinelearning/requirements.txt` | +1 dependency (pyarrow) |
| `main/daily_handlers.go` | Webhook handler calls Python upgrade-tier endpoint |
| `main/daily_scheduler.go` | Scheduler calls Python populate-daily endpoint |

### Database changes
None — all tables were created in Phase 1 migration (`001_phase1_tables.sql`).

---

## What Phase 2 Does NOT Include

These are deferred to Phase 3+:

- Web UI enhancements (artist profile cards, what-if composer UI, daily discovery page)
- CVAE model improvements (continuous targets, hard constraint steering)
- Era/decade features for link predictor
- GNN-based link predictor
- Online learning from feedback
- Per-genre model training
- Spotify playlist auto-creation from what-if results
- Enterprise custom model training
