# Phase 1: API Launch - Technical Implementation Plan

> **Source**: INTERLUDE_SERVICE_STRATEGY.md, Section 6.4 Phase 1 (Weeks 1-4)
> **Goal**: Clean up existing endpoints, add auth middleware, deploy behind TLS, publish OpenAPI docs
> **Constraint**: All existing models (v1, v2, v3, v5, CVAE) remain untouched and plug-and-play switchable

---

## Step 1: Model Registry & Plug-and-Play Versioning

### What We're Building
A lightweight model registry that lets any request specify which model version to use at runtime, without touching the trained model files.

### Current State
- Models stored as flat files: `logit_model_v1.joblib`, `logit_model_v3.joblib`, `logit_model_v5.joblib`
- CVAE stored as `model.pt` + `meta.json` + `prep.pkl` in `features/`
- `config.py` has `LOGIT_MODEL_VERSION = "v5"` as a hardcoded default
- Endpoints accept `model_version` param but loading is tightly coupled to config constants

### Technical Implementation

#### 1.1 Model Registry Module
**File**: `machinelearning/models/model_registry.py`

```python
"""
Model registry for plug-and-play model switching.
Does NOT modify any existing model files or training code.
Loads models lazily and caches them in memory.
"""
import os
import joblib
import torch
from pathlib import Path
from threading import Lock

MODEL_DIR = Path(__file__).parent.parent / "feature_engineering"

# Maps model_version string -> loader function + file path
LOGIT_REGISTRY = {
    "v1": MODEL_DIR / "logit_model_v1.joblib",
    "v2": MODEL_DIR / "logit_model_v2.joblib",
    "v3": MODEL_DIR / "logit_model_v3.joblib",
    "v5": MODEL_DIR / "logit_model_v5.joblib",
}

CVAE_REGISTRY = {
    "v1": MODEL_DIR / "features",  # contains model.pt, meta.json, prep.pkl
}

DEFAULT_LOGIT = os.getenv("DEFAULT_LOGIT_VERSION", "v5")
DEFAULT_CVAE = os.getenv("DEFAULT_CVAE_VERSION", "v1")

class ModelCache:
    """Thread-safe lazy model loader. Models loaded once, cached forever."""
    def __init__(self):
        self._cache = {}
        self._lock = Lock()

    def get_logit(self, version: str = None):
        version = version or DEFAULT_LOGIT
        key = f"logit_{version}"
        if key not in self._cache:
            with self._lock:
                if key not in self._cache:
                    path = LOGIT_REGISTRY.get(version)
                    if not path or not path.exists():
                        raise ValueError(
                            f"Model version '{version}' not found. "
                            f"Available: {list(LOGIT_REGISTRY.keys())}"
                        )
                    self._cache[key] = joblib.load(path)
        return self._cache[key], version

    def get_cvae(self, version: str = None):
        version = version or DEFAULT_CVAE
        key = f"cvae_{version}"
        if key not in self._cache:
            with self._lock:
                if key not in self._cache:
                    path = CVAE_REGISTRY.get(version)
                    if not path or not path.exists():
                        raise ValueError(
                            f"CVAE version '{version}' not found. "
                            f"Available: {list(CVAE_REGISTRY.keys())}"
                        )
                    # Load using existing track_feature_predictor logic
                    from models.track_feature_predictor import load_cvae_from_dir
                    self._cache[key] = load_cvae_from_dir(path)
        return self._cache[key], version

    def list_available(self):
        return {
            "logit": list(LOGIT_REGISTRY.keys()),
            "cvae": list(CVAE_REGISTRY.keys()),
            "defaults": {"logit": DEFAULT_LOGIT, "cvae": DEFAULT_CVAE},
        }

# Singleton instance
registry = ModelCache()
```

#### 1.2 How Plug-and-Play Works

**Adding a new model**: Drop a new `.joblib` file (e.g., `logit_model_v6.joblib`) into `feature_engineering/` and add one line to `LOGIT_REGISTRY`. No other code changes.

**Switching default at runtime**: Set env var `DEFAULT_LOGIT_VERSION=v3` to make v3 the default without code changes.

**Per-request override**: Any API call can pass `model_version: "v3"` to use a specific version for that request only.

**A/B testing** (from Strategy 4.2): Run the same request against two versions and compare outputs. The registry supports loading multiple versions simultaneously in memory.

#### 1.3 New Endpoint: Model Info
```
GET /api/v1/models
```
Returns available model versions, defaults, and metadata. Enables clients to discover what's available before making prediction requests.

### Scale Considerations
- Models are small (7-30KB for logit, ~few MB for CVAE) - all fit in memory simultaneously
- `Lock()` only blocks on first load; subsequent calls hit cache with no contention
- For future large models (e.g., GNN from Strategy 4.2), add an LRU eviction policy

---

## Step 2: API Endpoint Cleanup & Standardization

### What We're Building
Standardize all endpoints under `/api/v1/` with consistent request/response schemas, proper error handling, and model version in every response.

### Current State
- Endpoints use mixed prefixes: `/ml/predict/`, `/ml/generate/`, `/interlude/`
- Response schemas vary per endpoint
- No consistent error format
- Model version not always returned in response

### Technical Implementation

#### 2.1 Unified API Router Structure
**File**: `machinelearning/routers/v1.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from models.model_registry import registry

v1 = APIRouter(prefix="/api/v1")

# ---------- Prediction ----------
@v1.post("/predict/connection")
async def predict_connection(req: ConnectionRequest):
    """Predict collaboration probability between two artists."""
    model, version = registry.get_logit(req.model_version)
    # ... existing link_predictor logic, unchanged ...
    return ConnectionResponse(
        probability=prob,
        model_version=version,
        features_used=feature_dict,
        latency_ms=elapsed,
    )

@v1.post("/predict/neighbors")
async def predict_neighbors(req: NeighborRequest):
    """Get top-k predicted neighbors for one artist."""
    model, version = registry.get_logit(req.model_version)
    # ... existing neighbor logic, unchanged ...

@v1.post("/predict/batch")
async def predict_batch(req: BatchRequest):
    """Bulk prediction for multiple artist pairs."""
    # New endpoint - iterates over pairs using same predict logic

# ---------- Generation ----------
@v1.post("/generate/tracks")
async def generate_tracks(req: TrackGenRequest):
    """Generate synthetic track features for an artist pair."""
    cvae, version = registry.get_cvae(req.model_version)
    # ... existing CVAE generation logic, unchanged ...

@v1.post("/generate/playlist")
async def generate_playlist(req: PlaylistRequest):
    """Map synthetic tracks to real tracks via Aitchison similarity."""
    # Wraps existing synthetic-tracks-similarity logic

# ---------- Discovery ----------
@v1.get("/models")
async def list_models():
    """List available model versions and defaults."""
    return registry.list_available()

@v1.get("/artist/{artist_id}/profile")
async def artist_profile(artist_id: str):
    """Comprehensive artist profile combining all data sources."""
    # New endpoint - aggregates from artist, lastfm_stats, genre_proportions, embeddings
```

#### 2.2 Backward Compatibility
The old endpoints (`/ml/predict/artist-link`, etc.) remain active but return a `Deprecation` header pointing to the v1 equivalents. They are thin wrappers that call the same underlying logic.

#### 2.3 Standardized Response Envelope

Every response includes:
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

Every error returns:
```json
{
  "error": {
    "code": "ARTIST_NOT_FOUND",
    "message": "No artist found with ID 'xyz'",
    "request_id": "uuid"
  }
}
```

#### 2.4 Pydantic Schemas (New/Updated)

**File**: `machinelearning/schemas/v1.py`

```python
from pydantic import BaseModel, Field
from typing import Optional

class ConnectionRequest(BaseModel):
    src_artist: str            # MBID, Spotify ID, or name
    dst_artist: str
    model_version: Optional[str] = None  # None = use default

class ConnectionResponse(BaseModel):
    probability: float
    model_version: str
    features_used: dict
    latency_ms: float

class NeighborRequest(BaseModel):
    artist: str
    limit: int = Field(default=20, le=100)
    min_probability: Optional[float] = None
    genre_filter: Optional[list[str]] = None
    model_version: Optional[str] = None

class BatchRequest(BaseModel):
    pairs: list[dict]          # [{"src": str, "dst": str}, ...]
    model_version: Optional[str] = None

class TrackGenRequest(BaseModel):
    src_artist: str
    dst_artist: str
    num_tracks: int = Field(default=5, le=20)
    model_version: Optional[str] = None

class ArtistProfile(BaseModel):
    name: str
    mbid: str
    spotify_id: Optional[str]
    popularity: Optional[float]
    genre_distribution: dict
    collab_count: int
    top_collabs: list[dict]
    embedding_available: bool
```

### Scale Considerations
- Batch endpoint caps at 1000 pairs per request (configurable per tier later)
- All endpoints return `request_id` for tracing and debugging
- Pydantic v2 validation is fast (<1ms per request)

---

## Step 3: Authentication & Rate Limiting Middleware

### What We're Building
API key authentication with tier-based rate limiting. Free tier gets 100 req/hr, with upgrade path.

### Current State
- Go frontend has `X-SDS-Token` anti-scrape tokens (short-lived, browser session only)
- No API key system for programmatic access
- No rate limiting beyond in-flight dedup on Go side

### Technical Implementation

#### 3.1 Database Tables
Run against `musicbrainz_db`:

```sql
CREATE TABLE api_users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    org_name TEXT,
    tier TEXT NOT NULL DEFAULT 'free',  -- 'free', 'researcher', 'enterprise'
    api_key_hash TEXT UNIQUE NOT NULL,
    rate_limit_per_hour INT NOT NULL DEFAULT 100,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_active TIMESTAMPTZ
);

CREATE TABLE api_usage_log (
    log_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id UUID REFERENCES api_users(user_id),
    endpoint TEXT NOT NULL,
    method TEXT NOT NULL,
    status_code INT,
    latency_ms FLOAT,
    request_params JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_api_usage_user_date ON api_usage_log(user_id, created_at);
```

#### 3.2 Auth Middleware (FastAPI)
**File**: `machinelearning/middleware/auth.py`

```python
"""
API key authentication middleware.
- Checks X-API-Key header against api_users table
- Enforces rate limits per tier
- Logs all requests to api_usage_log
- Exempts internal calls from Go service (via shared internal secret)
"""
import hashlib
import time
from collections import defaultdict
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

# In-memory sliding window rate limiter
# For production: replace with Redis-backed counter
class RateLimiter:
    def __init__(self):
        self._windows = defaultdict(list)  # user_id -> [timestamps]

    def check(self, user_id: str, limit: int) -> bool:
        now = time.time()
        window = self._windows[user_id]
        # Remove entries older than 1 hour
        window[:] = [t for t in window if now - t < 3600]
        if len(window) >= limit:
            return False
        window.append(now)
        return True

    def remaining(self, user_id: str, limit: int) -> int:
        now = time.time()
        window = self._windows[user_id]
        window[:] = [t for t in window if now - t < 3600]
        return max(0, limit - len(window))

rate_limiter = RateLimiter()

INTERNAL_SECRET = os.getenv("INTERNAL_SERVICE_SECRET", "")
PUBLIC_PATHS = {"/docs", "/openapi.json", "/redoc", "/api/v1/models", "/health"}

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip auth for public paths
        if path in PUBLIC_PATHS or path.startswith("/ml/"):  # legacy endpoints keep old auth
            return await call_next(request)

        # Internal service-to-service calls (Go -> Python)
        internal_key = request.headers.get("X-Internal-Secret")
        if internal_key and internal_key == INTERNAL_SECRET:
            return await call_next(request)

        # API key auth
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            raise HTTPException(status_code=401, detail="Missing X-API-Key header")

        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        user = await lookup_user_by_key(key_hash)  # DB query
        if not user:
            raise HTTPException(status_code=401, detail="Invalid API key")

        # Rate limit check
        if not rate_limiter.check(str(user["user_id"]), user["rate_limit_per_hour"]):
            remaining = rate_limiter.remaining(str(user["user_id"]), user["rate_limit_per_hour"])
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Limit: {user['rate_limit_per_hour']}/hr",
                headers={"X-RateLimit-Remaining": str(remaining)},
            )

        # Attach user to request state for downstream use
        request.state.user = user
        request.state.request_id = str(uuid.uuid4())

        start = time.time()
        response = await call_next(request)
        latency = (time.time() - start) * 1000

        # Log usage (fire-and-forget, don't block response)
        await log_usage(user["user_id"], path, request.method, response.status_code, latency)

        # Add rate limit headers
        remaining = rate_limiter.remaining(str(user["user_id"]), user["rate_limit_per_hour"])
        response.headers["X-RateLimit-Limit"] = str(user["rate_limit_per_hour"])
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-Request-ID"] = request.state.request_id

        return response
```

#### 3.3 API Key Generation Endpoint

```python
@v1.post("/auth/register")
async def register_api_user(email: str, org_name: str = None):
    """Register for a free-tier API key."""
    api_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    # Insert into api_users with tier='free'
    # Return the raw API key ONCE (never stored in plaintext)
    return {"api_key": api_key, "tier": "free", "rate_limit_per_hour": 100}
```

#### 3.4 Go Frontend Integration
The Go frontend continues using its existing `X-SDS-Token` for browser sessions. When proxying to the ML service, it passes `X-Internal-Secret` to bypass API key auth:

```go
// In machine_learning_handlers.go - add to existing proxy logic:
req.Header.Set("X-Internal-Secret", os.Getenv("INTERNAL_SERVICE_SECRET"))
```

### Scale Considerations
- In-memory rate limiter works for single-instance deployment (Phase 1)
- Phase 2+ migrates to Redis for multi-instance support
- `api_usage_log` is append-only; partition by month for long-term retention
- API key is shown once on registration, only the hash is stored

---

## Step 4: Metrics & Monitoring (from Strategy Section 4.3)

### What We're Building
Instrumentation for the three metric categories defined in the strategy: Model Quality, System Health, and Business Metrics.

### Technical Implementation

#### 4.1 Prometheus Metrics Exporter
**File**: `machinelearning/middleware/metrics.py`

```python
"""
Prometheus metrics for FastAPI ML service.
Exposes /metrics endpoint for scraping.
"""
from prometheus_client import Counter, Histogram, Gauge, Summary

# ---- System Health (Strategy 4.3) ----
REQUEST_LATENCY = Histogram(
    "interlude_request_latency_seconds",
    "Request latency by endpoint",
    ["endpoint", "method", "status"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

CACHE_HITS = Counter(
    "interlude_cache_hits_total",
    "Cache hits (fast path) vs misses (slow path)",
    ["cache_type", "hit"],  # cache_type: prediction, embedding, profile
)

REQUEST_ERRORS = Counter(
    "interlude_request_errors_total",
    "Request errors by endpoint and error type",
    ["endpoint", "error_type"],  # error_type: validation, not_found, model_error, rate_limit
)

DB_QUERY_DURATION = Histogram(
    "interlude_db_query_seconds",
    "Database query duration",
    ["query_name"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.5, 1.0],
)

# ---- Model Quality (Strategy 4.3) ----
PREDICTION_DISTRIBUTION = Histogram(
    "interlude_prediction_probability",
    "Distribution of prediction probabilities",
    ["model_version"],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

GENRE_DIVERSITY = Gauge(
    "interlude_prediction_genre_diversity",
    "Genre diversity score of recent predictions (rolling window)",
    ["model_version"],
)

# ---- Business Metrics (Strategy 4.3) ----
API_CALLS_BY_USER = Counter(
    "interlude_api_calls_total",
    "API calls by user tier and endpoint",
    ["tier", "endpoint"],
)

PLAYLIST_CREATIONS = Counter(
    "interlude_playlist_creations_total",
    "Spotify playlists created from synthetic tracks",
)

DATASET_EXPORTS = Counter(
    "interlude_dataset_exports_total",
    "Dataset export requests by format",
    ["format"],  # csv, parquet
)
```

#### 4.2 Metrics Collection Points

| Metric (from Strategy 4.3) | Where Collected | How |
|---|---|---|
| **Precision@k** for neighbor predictions | Offline batch job (weekly) | Compare top-k predictions against new real collabs from MusicBrainz |
| **NDCG** for ranking quality | Offline batch job (weekly) | Evaluate ranking against ground truth |
| **Calibration curve** | Offline batch job (weekly) | Bin predictions by probability, measure actual collab rate per bin |
| **Genre diversity of predictions** | In prediction endpoint | Count unique genres in top-k results, emit to `GENRE_DIVERSITY` gauge |
| **P50/P95/P99 latency** | Auth middleware | `REQUEST_LATENCY` histogram auto-computes percentiles |
| **Cache hit rate** | Prediction handler | Increment `CACHE_HITS` on DB lookup hit/miss |
| **Error rate by endpoint** | Error handler | `REQUEST_ERRORS` counter |
| **DB query timing** | Database utility functions | Wrap queries with `DB_QUERY_DURATION` |
| **API calls per user per day** | Auth middleware | `API_CALLS_BY_USER` counter + `api_usage_log` table |
| **Playlist creation rate** | Playlist endpoint | `PLAYLIST_CREATIONS` counter |
| **Dataset export volume** | Export endpoint | `DATASET_EXPORTS` counter |
| **User retention (DAU/MAU)** | Offline query on `api_usage_log` | SQL: distinct users per day vs per month |

#### 4.3 Health Check Endpoint
```
GET /health
```
Returns:
```json
{
  "status": "healthy",
  "models_loaded": ["logit_v5", "cvae_v1"],
  "db_connected": true,
  "uptime_seconds": 86400,
  "version": "1.0.0"
}
```

### Scale Considerations
- Prometheus scrape interval: 15s (standard)
- `api_usage_log` provides durable audit trail; Prometheus provides real-time dashboards
- Model quality metrics run as offline batch jobs to avoid impacting request latency
- Grafana dashboards built on Prometheus data (reference: Strategy mentions Grafana)

---

## Step 5: Model Improvement Integration (from Strategy Section 4.2)

### What We're Building
Infrastructure to support the 4.2 recommended improvements WITHOUT changing existing models. Each improvement is a new model version that enters the registry alongside existing ones.

### Improvement Roadmap (Prioritized from Strategy 4.2)

#### 5.1 Era/Decade Features (HIGH priority, MEDIUM effort)

**What**: Add `active_decade_start`, `active_decade_end`, `decade_overlap` to feature vector for new model versions.

**How it stays plug-and-play**:
1. Add era columns to the feature engineering pipeline as new feature group `era`
2. Train a new model (e.g., `logit_model_v6.joblib`) with era features included
3. Drop `logit_model_v6.joblib` into `feature_engineering/`
4. Add one line to `LOGIT_REGISTRY`: `"v6": MODEL_DIR / "logit_model_v6.joblib"`
5. Test: `curl -X POST /api/v1/predict/connection -d '{"src_artist": "...", "dst_artist": "...", "model_version": "v6"}'`
6. If v6 is better, set `DEFAULT_LOGIT_VERSION=v6`. If not, keep v5. Both remain available.

**Data source**: MusicBrainz `artist.begin_date_year`, `artist.end_date_year`

#### 5.2 Continuous CVAE Targets (HIGH priority, MEDIUM effort)

**What**: Add Spotify audio features (energy, valence, loudness, tempo) as continuous targets alongside the existing 62 binary features.

**How it stays plug-and-play**:
1. Fetch Spotify audio features via existing `artist_mbid_spotify` mapping
2. Add continuous columns to `cvae_config.py` `Y_CONT_COLS` (currently empty)
3. Train CVAE v2 with mixed binary+continuous targets
4. Save as new directory: `feature_engineering/features_v2/` (model.pt, meta.json, prep.pkl)
5. Add to `CVAE_REGISTRY`: `"v2": MODEL_DIR / "features_v2"`
6. v1 and v2 both available simultaneously

#### 5.3 Stratified Negative Sampling (HIGH priority, LOW effort)

**What**: When sampling non-collaborating pairs for training, stratify by genre cluster instead of random sampling. Reduces popularity bias (Strategy 4.1 issue #1).

**How it stays plug-and-play**:
1. Modify `features/sampling.py` to add a `stratified=True` option
2. Generate new training data with stratified negatives
3. Train new logit model (v7) on stratified data
4. Register as `"v7"` in `LOGIT_REGISTRY`
5. Compare v7 vs v5 using A/B test endpoint

#### 5.4 A/B Testing Endpoint (MEDIUM priority, LOW effort)

**What**: Compare two model versions on the same input.

```
POST /api/v1/predict/compare
```
**Input**: `{ src_artist, dst_artist, versions: ["v5", "v6"] }`
**Output**: `{ results: [{ version: "v5", probability: 0.82, ... }, { version: "v6", probability: 0.74, ... }] }`

This directly supports Strategy 4.2 item: "A/B test PU learning vs. standard logistic regression"

#### 5.5 Artist Type Features (MEDIUM priority, LOW effort)

**What**: Add `artist_type` (person, group, orchestra, choir, character) from MusicBrainz.

**Data source**: `artist.type` column in MusicBrainz schema. One-hot encode into feature vector.

#### 5.6 Genre-Specific Models (MEDIUM priority, HIGH effort)

**What**: Train separate logit models per genre cluster (rock, hip-hop, electronic, etc.)

**How it stays plug-and-play**:
1. Train per-genre models: `logit_model_rock_v1.joblib`, `logit_model_hiphop_v1.joblib`
2. Extend registry to support genre-scoped versions
3. Routing logic: determine genre of src_artist, select genre-specific model
4. Fallback: use general model if genre model unavailable

### Scale Considerations
- Each new model version is independent; no migration needed
- Old models never deleted, ensuring reproducibility
- Model metadata (training date, features, performance) tracked in `predict_connection_model` table
- Retraining is a separate offline job, never blocks serving

---

## Step 6: Security Hardening (from Strategy Section 5.4)

### What We're Building
Address the CRITICAL security items from the strategy before any public-facing deployment.

### Technical Implementation

#### 6.1 Remove Hardcoded Credentials

**config.py changes**:
```python
# BEFORE (insecure):
# LASTFM_API_KEY = "abc123..."
# DB_URL = "postgres://postgres:password@localhost..."

# AFTER:
LASTFM_API_KEY = os.environ["LASTFM_API_KEY"]
LASTFM_API_SECRET = os.environ["LASTFM_API_SECRET"]
SPOTIFY_CLIENT_ID = os.environ["SPOTIFY_CLIENT_ID"]
SPOTIFY_CLIENT_SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]
DB_URL = os.environ["PG_DSN"]
```

All secrets loaded from environment variables. App fails fast on startup if any are missing.

#### 6.2 .env File Setup
```bash
# .env (NOT committed to git, already in .gitignore)
PG_DSN=postgresql://postgres:****@localhost:5432/musicbrainz_db
LASTFM_API_KEY=****
LASTFM_API_SECRET=****
SPOTIFY_CLIENT_ID=****
SPOTIFY_CLIENT_SECRET=****
INTERNAL_SERVICE_SECRET=****
SDS_TOKEN_SECRET=****
```

#### 6.3 Input Validation
Add format validation to all artist ID inputs:
```python
def resolve_artist_id(raw: str) -> int:
    """Accept MBID (UUID), Spotify ID, or name. Validate format before DB query."""
    if UUID_REGEX.match(raw):
        return lookup_by_mbid(raw)
    elif SPOTIFY_ID_REGEX.match(raw):
        return lookup_by_spotify(raw)
    else:
        # Name-based lookup, sanitized
        return lookup_by_name(raw.strip()[:200])
```

#### 6.4 TLS Deployment
```yaml
# docker-compose.yml addition:
services:
  caddy:
    image: caddy:2
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
    depends_on:
      - api
      - ml
```

```
# Caddyfile
interlude.api.yourdomain.com {
    reverse_proxy /api/* ml:8000
    reverse_proxy /* api:8080
}
```

---

## Step 7: OpenAPI Documentation

### What We're Building
Auto-generated, browsable API docs published at `/docs` (Swagger) and `/redoc`.

### Current State
FastAPI already generates OpenAPI at `/docs` but it reflects the old endpoint structure and lacks descriptions.

### Technical Implementation

#### 7.1 App Metadata
```python
app = FastAPI(
    title="Interlude - Artist Collaboration Prediction API",
    description="""
    Predict artist collaborations, generate synthetic tracks,
    and discover new music connections.

    ## Authentication
    Pass your API key in the `X-API-Key` header.
    Get a free key at POST /api/v1/auth/register.

    ## Model Versions
    All prediction endpoints accept an optional `model_version` parameter.
    See GET /api/v1/models for available versions.
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)
```

#### 7.2 Endpoint Documentation
Each endpoint gets:
- Summary (short, shown in sidebar)
- Description (detailed, shown when expanded)
- Request/response examples
- Error response schemas
- Tags for grouping (Prediction, Generation, Discovery, Admin)

---

## Final Output: What Phase 1 Delivers

At the end of Phase 1, the service exposes:

| Endpoint | Status | Auth Required |
|---|---|---|
| `GET /health` | New | No |
| `GET /docs` | Enhanced | No |
| `GET /api/v1/models` | New | No |
| `POST /api/v1/auth/register` | New | No |
| `POST /api/v1/predict/connection` | Refactored | API Key |
| `POST /api/v1/predict/neighbors` | Refactored | API Key |
| `POST /api/v1/predict/batch` | New | API Key |
| `POST /api/v1/predict/compare` | New | API Key |
| `POST /api/v1/generate/tracks` | Refactored | API Key |
| `POST /api/v1/generate/playlist` | Refactored | API Key |
| `GET /api/v1/artist/{id}/profile` | New | API Key |
| `GET /metrics` | New | Internal |
| `/ml/*` (legacy) | Unchanged | SDS Token |

**Infrastructure**:
- TLS termination via Caddy
- API key auth + tier-based rate limiting
- Prometheus metrics for all 4.3 categories
- Model registry supporting v1, v2, v3, v5 logit + v1 CVAE simultaneously
- All credentials in environment variables
- Standardized JSON response format

**Unchanged**:
- All existing model files (`.joblib`, `.pt`)
- All existing training code
- Go frontend and its auth flow
- Database schema (only new tables added, none modified)
- Docker Compose structure (only Caddy service added)

---

## Build Order (Week-by-Week)

| Week | Steps | Deliverable |
|------|-------|-------------|
| **Week 1** | Step 1 (Model Registry) + Step 6 (Security) | Models are plug-and-play, credentials secured |
| **Week 2** | Step 2 (Endpoint Cleanup) + Step 3 (Auth Middleware) | v1 API live with key auth |
| **Week 3** | Step 4 (Metrics) + Step 5 (Model Improvement Infra) | Monitoring active, A/B compare endpoint ready |
| **Week 4** | Step 7 (OpenAPI Docs) + Integration Testing + TLS Deploy | Phase 1 complete, ready for free tier launch |
