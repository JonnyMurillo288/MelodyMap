# Phase 1 Implementation Changelog

> **Date**: 2026-03-28
> **Branch**: claude_branch
> **Source Plan**: PHASE1_IMPLEMENTATION.md / INTERLUDE_SERVICE_STRATEGY.md

---

## Overview

Phase 1 of the Interlude service go-to-market is now implemented. This covers everything needed to launch the public API: model registry, standardized endpoints, authentication, rate limiting, monitoring, TLS, and credential security.

All existing models and legacy endpoints remain untouched. Nothing breaks.

---

## What Was Implemented

### 1. Model Registry — Plug-and-Play Versioning

**File**: `machinelearning/models/model_registry.py`

The core requirement was that existing models (v1, v2, v3, v5 logit + v1 CVAE) stay as-is and can be swapped at any time. The registry does this:

- **Lazy loading**: Models load on first request, then stay cached in memory for the process lifetime. Thread-safe via `Lock`.
- **Per-request switching**: Any API call can pass `model_version: "v3"` to use a specific version. If omitted, uses the default (v5).
- **Env var override**: Set `DEFAULT_LOGIT_VERSION=v3` to change the default without touching code.
- **Adding new models**: Drop a `.joblib` file into `feature_engineering/`, add one line to `LOGIT_REGISTRY`. Same for CVAE — add a directory to `CVAE_REGISTRY`.
- **Discovery endpoint**: `GET /api/v1/models` returns available versions, defaults, and what's currently loaded.

**How it connects**: The v1 router calls `registry.get_logit(req.model_version)` instead of hardcoding a path. The old `/ml/*` endpoints still load models the old way — they were not modified.

---

### 2. Credential Security

**File modified**: `machinelearning/config/config.py`

Addressed the CRITICAL security item from INTERLUDE_SERVICE_STRATEGY.md Section 5.4:

| Before | After |
|---|---|
| LastFM API key hardcoded as string literal | `os.environ.get("LASTFM_API_KEY", "")` |
| LastFM secret hardcoded as string literal | `os.environ.get("LASTFM_API_SECRET", "")` |
| Spotify client_id had hardcoded fallback | `os.environ.get("SPOTIFY_CLIENT_ID", "")` |
| Spotify client_secret had hardcoded fallback | `os.environ.get("SPOTIFY_CLIENT_SECRET", "")` |

Added `INTERNAL_SERVICE_SECRET` config for service-to-service auth.

The actual credential values were moved to `.env.docker` (already gitignored) and a `.env.example` template was created for onboarding.

---

### 3. Standardized API Schemas

**File**: `machinelearning/schemas/v1.py`

Every v1 endpoint now uses typed Pydantic v2 schemas. All responses share a standard envelope:

```json
{
  "data": { ... },
  "meta": {
    "model_version": "v5",
    "latency_ms": 42.3,
    "cached": false,
    "request_id": "uuid"
  }
}
```

Schemas implemented:
- `ConnectionRequest` / `ConnectionData` — single pair prediction
- `NeighborRequest` / `NeighborsData` — top-k neighbor discovery
- `BatchRequest` / `BatchData` — bulk prediction (up to 1000 pairs)
- `CompareRequest` / `CompareData` — A/B model comparison (Strategy 4.2)
- `TrackGenRequest` / `TrackGenData` — CVAE synthetic track generation
- `PlaylistRequest` / `PlaylistData` — Aitchison similarity matching
- `ArtistProfileData` — full artist profile aggregation
- `RegisterRequest` / `RegisterResponse` — API key registration
- `FeedbackRequest` — prediction quality feedback (Strategy 4.2)
- `HealthData` / `ModelInfoData` — system status

---

### 4. Authentication & Rate Limiting Middleware

**File**: `machinelearning/middleware/auth.py`

Three auth paths coexist:

| Path | Auth Method | Who Uses It |
|---|---|---|
| `/api/v1/*` | `X-API-Key` header (hashed, checked against `api_users` table) | External API consumers |
| `/ml/*`, `/interlude/*` | Existing `X-SDS-Token` (unchanged) | Go frontend / browser |
| Internal (Go -> Python) | `X-Internal-Secret` header | Docker service-to-service |

**Rate limiting**: In-memory sliding window per user. Limits by tier:
- Free: 100 requests/hour
- Researcher: 1,000/hour
- Enterprise: 10,000/hour

Rate limit info returned in response headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`.

**Usage logging**: Every authenticated request is logged to `api_usage_log` table with endpoint, method, status code, and latency.

**Registration**: `POST /api/v1/auth/register` creates a free-tier user, returns the raw API key once. Only the SHA-256 hash is stored.

---

### 5. Prometheus Metrics (Strategy 4.3)

**File**: `machinelearning/middleware/metrics.py`

Instrumented all three metric categories from the strategy:

**Model Quality metrics**:
- `interlude_prediction_probability` — histogram of output probabilities per model version (detects calibration drift)
- `interlude_prediction_genre_diversity` — gauge tracking unique genres in predictions (detects popularity collapse)

**System Health metrics**:
- `interlude_request_latency_seconds` — P50/P95/P99 latency per endpoint (histogram with 10 buckets)
- `interlude_cache_hits_total` — fast path vs slow path ratio
- `interlude_request_errors_total` — errors by endpoint and type
- `interlude_db_query_seconds` — database query timing
- `interlude_requests_in_progress` — concurrent request gauge

**Business metrics**:
- `interlude_api_calls_total` — calls by user tier and endpoint
- `interlude_playlist_creations_total` — Spotify playlist creation count
- `interlude_dataset_exports_total` — export requests by format
- `interlude_feedback_submissions_total` — feedback volume

**Endpoint**: `GET /metrics` returns Prometheus-formatted text for scraping.

The `MetricsMiddleware` auto-instruments every request. Endpoint handlers call helper functions (`observe_prediction`, `observe_cache`, etc.) for domain-specific metrics.

---

### 6. v1 API Router — All Endpoints

**File**: `machinelearning/routers/v1.py`

Every endpoint from INTERLUDE_SERVICE_STRATEGY.md Section 2.2 that maps to Phase 1:

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/models` | GET | List available model versions and defaults |
| `/api/v1/health` | GET | Health check (DB connection, loaded models) |
| `/api/v1/auth/register` | POST | Register for free-tier API key |
| `/api/v1/predict/connection` | POST | Predict collaboration probability for one artist pair |
| `/api/v1/predict/neighbors` | POST | Get top-k predicted neighbors for one artist |
| `/api/v1/predict/batch` | POST | Bulk prediction for up to 1000 pairs |
| `/api/v1/predict/compare` | POST | A/B test multiple model versions on same input (Strategy 4.2) |
| `/api/v1/generate/tracks` | POST | Generate synthetic tracks via CVAE |
| `/api/v1/generate/playlist` | POST | Find real tracks similar to synthetic tracks |
| `/api/v1/artist/{id}/profile` | GET | Full artist profile (metadata, popularity, genres, collabs, embedding status) |
| `/api/v1/feedback` | POST | Submit feedback on prediction quality (Strategy 4.2) |

**Key design decisions**:
- All endpoints use the model registry. No model path is hardcoded in the router.
- Prediction endpoints check the DB cache first (fast path), fall back to full ML pipeline (slow path), and record cache hit/miss metrics.
- The `compare` endpoint loads multiple model versions simultaneously and returns side-by-side results. This directly enables Strategy 4.2 A/B testing.
- Artist resolution accepts MBID (UUID), integer ID, or plain name — tries each format in order.
- Legacy `/ml/*` endpoints were NOT modified. They continue working identically.

---

### 7. app.py Integration

**File modified**: `machinelearning/app.py`

Three additions to the existing FastAPI app initialization:

1. **Middleware stack**: `MetricsMiddleware` wraps `AuthMiddleware` wraps all handlers. Order matters — metrics captures auth-rejected requests too.
2. **Router mount**: `app.include_router(v1)` adds all `/api/v1/*` routes alongside existing `/ml/*` routes.
3. **Startup hook**: `registry.preload_defaults()` eagerly loads the default logit (v5) and CVAE (v1) models on server start so first requests don't pay cold-start cost.

The app description and docs were updated to explain the auth flow and model versioning to API consumers viewing `/docs`.

---

### 8. Go Frontend — Internal Auth Header

**Files modified**: `machine_learning_handlers.go`, `daily_handlers.go`, `daily_scheduler.go`

Every place the Go frontend makes an HTTP request to the Python ML service (6 call sites total) now attaches:

```go
if secret := os.Getenv("INTERNAL_SERVICE_SECRET"); secret != "" {
    req.Header.Set("X-Internal-Secret", secret)
}
```

This lets the Go service bypass API key auth when calling the ML service internally. The shared secret is set via `.env.docker` and passed through `docker-compose.yml`.

---

### 9. Database Migration

**File**: `machinelearning/migrations/001_phase1_tables.sql`

New tables (all `CREATE TABLE IF NOT EXISTS` — safe to re-run):

| Table | Purpose |
|---|---|
| `api_users` | API key storage (hashed), tier, rate limits, email |
| `api_usage_log` | Per-request audit trail (user, endpoint, latency, status) |
| `prediction_feedback` | User ratings on predictions (1-5 scale + comments) |
| `daily_predictions` | Cache for daily genre-based predictions (Spotle) |
| `scenario_cache` | TTL-based cache for what-if scenarios |
| `dataset_exports` | Audit trail for data export requests |

Run with: `psql -U postgres -d musicbrainz_db -f migrations/001_phase1_tables.sql`

---

### 10. TLS / Reverse Proxy

**Files**: `Caddyfile`, `docker-compose.yml`

Caddy added as a third Docker service. Routes:
- `/api/v1/*`, `/metrics`, `/docs`, `/redoc`, `/health`, `/ml/*`, `/interlude/*` -> ML service (port 8000)
- Everything else -> Go frontend (port 8080)

Caddy auto-provisions TLS. For production, change `localhost` in the Caddyfile to your real domain and Caddy handles Let's Encrypt certificates automatically.

---

### 11. Docker & Environment

**docker-compose.yml changes**:
- ML service now receives `INTERNAL_SERVICE_SECRET`, `LASTFM_API_KEY`, `LASTFM_API_SECRET`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `DEFAULT_LOGIT_VERSION`, `DEFAULT_CVAE_VERSION` from the host env / `.env.docker`
- API (Go) service receives `INTERNAL_SERVICE_SECRET`
- Caddy service added with persistent volumes for cert storage

**requirements.txt**: Added `prometheus-client==0.21.0`

**.env.example**: Template with all required env vars and placeholder values. Safe to commit — contains no real secrets.

**.env.docker**: Updated with actual secret values for local dev (already gitignored).

---

## What Was NOT Changed

- No existing model files (`.joblib`, `.pt`, `.pkl`) were modified
- No existing training code was modified
- No existing `/ml/*` or `/interlude/*` endpoint logic was changed
- No existing database tables were altered
- No existing Go frontend routes were changed
- No existing auth flow (Spotify OAuth, SDS tokens) was changed

---

## Startup Checklist

```bash
# 1. Run the migration (one time)
psql -U postgres -d musicbrainz_db -f internal/interlude_service/machinelearning/migrations/001_phase1_tables.sql

# 2. Make sure .env.docker has the required secrets (it does for local dev)

# 3. Build and start
docker compose up --build

# 4. Verify health
curl http://localhost:8002/api/v1/health

# 5. Register an API key
curl -X POST http://localhost:8002/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com"}'

# 6. Make a prediction
curl -X POST http://localhost:8002/api/v1/predict/connection \
  -H "X-API-Key: KEY_FROM_STEP_5" \
  -H "Content-Type: application/json" \
  -d '{"src_artist": "MBID", "dst_artist": "MBID"}'

# 7. Browse docs
open http://localhost:8002/docs

# 8. Check metrics
curl http://localhost:8002/metrics
```

---

## File Inventory

### New Files
```
machinelearning/models/model_registry.py
machinelearning/schemas/__init__.py
machinelearning/schemas/v1.py
machinelearning/middleware/__init__.py
machinelearning/middleware/auth.py
machinelearning/middleware/metrics.py
machinelearning/routers/__init__.py
machinelearning/routers/v1.py
machinelearning/migrations/001_phase1_tables.sql
Caddyfile
.env.example
```

### Modified Files
```
machinelearning/config/config.py          — credentials to env vars
machinelearning/app.py                    — middleware + router + registry wiring
machinelearning/requirements.txt          — added prometheus-client
main/machine_learning_handlers.go         — X-Internal-Secret header (3 sites)
main/daily_handlers.go                    — X-Internal-Secret header (2 sites)
main/daily_scheduler.go                   — X-Internal-Secret header (1 site)
docker-compose.yml                        — Caddy service + env var passthrough
.env.docker                               — new secret values
```
