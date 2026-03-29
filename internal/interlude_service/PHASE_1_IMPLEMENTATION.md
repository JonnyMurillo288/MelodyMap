# Phase 1: Implementation Plan — API Launch & Model Infrastructure

> **Source**: [INTERLUDE_SERVICE_STRATEGY.md](INTERLUDE_SERVICE_STRATEGY.md) §6.4 Phase 1 (Weeks 1–4)
> **Goal**: Clean up existing endpoints, build plug-and-play model versioning, add auth middleware, implement metrics, deploy behind TLS, publish OpenAPI docs.

---

## Table of Contents

1. [Plug-and-Play Model Registry](#1-plug-and-play-model-registry)
2. [Endpoint Cleanup & Versioned API](#2-endpoint-cleanup--versioned-api)
3. [Model Improvements (Strategy §4.2)](#3-model-improvements-strategy-42)
4. [Metrics & Monitoring (Strategy §4.3)](#4-metrics--monitoring-strategy-43)
5. [Auth Middleware & Rate Limiting](#5-auth-middleware--rate-limiting)
6. [Security Hardening](#6-security-hardening)
7. [Database Migrations](#7-database-migrations)
8. [Deployment & TLS](#8-deployment--tls)
9. [Final Output & Scale Targets](#9-final-output--scale-targets)

---

## 1. Plug-and-Play Model Registry

### 1.1 Problem

Today, model selection is hardcoded across multiple files:

```python
# config/config.py
LOGIT_MODEL_VERSION = "v5"
LOGIT_MODEL_ID = 5

# app.py — hardcoded path construction
logit_path = os.path.join(MODEL_ENGINEERING_DIR, f'logit_model_{LOGIT_MODEL_VERSION}.joblib')
```

Switching from v5 to v3 requires editing `config.py` and restarting the service. The CVAE has a single unversioned artifact at `feature_engineering/features/`.

### 1.2 What Exists on Disk (Don't Touch These)

```
feature_engineering/
├── logit_model_v1.joblib          # 20KB  — Jan 27
├── logit_model_v2.joblib          # 30KB  — Feb 4
├── logit_model_v3.joblib          # 8KB   — Feb 10  (18 features, includes genre similarity)
├── logit_model_v5.joblib          # 7KB   — Feb 11  (11 features, no genre similarity)
├── highlevel_pca_v1.joblib        # 17KB  — Jan 4
├── features/
│   ├── model.pt                   # CVAE v1 (1MB)
│   ├── prep.pkl                   # CVAE preprocessor
│   └── meta.json                  # CVAE metadata (z_dim=16, 7 C_COLS, 62 Y_BIN_COLS)
└── metadata/
    ├── logit_model_v1.json        # hyperparams + test metrics
    ├── logit_model_v2.json
    ├── logit_model_v3.json        # ROC AUC: 0.916, F1: 0.844, 18 features
    └── logit_model_v5.json        # ROC AUC: 0.916, F1: 0.843, 11 features
```

**Rule: None of these files are modified. New models are added alongside them. The registry reads whatever is on disk.**

### 1.3 Design: `ModelRegistry` Class

Create `machinelearning/models/registry.py`:

```python
"""
Plug-and-play model registry.

Scans the feature_engineering/ directory on startup and indexes all
available models. Any endpoint can request a specific version or fall
back to the configured default. Models are loaded lazily and cached
in memory.

USAGE:
    registry = ModelRegistry(base_dir="./feature_engineering")
    model = registry.get_logit("v5")           # specific version
    model = registry.get_logit()               # default (from config)
    model = registry.get_logit("v3")           # swap to v3 at runtime
    cvae  = registry.get_cvae("v1")            # CVAE model + prep + meta
"""

import os
import json
import joblib
from pathlib import Path
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from config.config import LOGIT_MODEL_VERSION, MODEL_ENGINEERING_DIR


@dataclass
class LogitEntry:
    version: str
    path: Path                          # path to .joblib
    metadata_path: Optional[Path]       # path to .json (hyperparams, metrics)
    features: list                      # feature column names
    test_metrics: dict                  # ROC AUC, F1, etc.
    _model: Any = field(default=None, repr=False)

    def load(self):
        """Lazy-load the model from disk. Cached after first call."""
        if self._model is None:
            from models.link_predictor import LinkPredictor
            self._model = LinkPredictor.load(self.path)
        return self._model


@dataclass
class CVAEEntry:
    version: str
    model_path: Path                    # model.pt
    prep_path: Path                     # prep.pkl
    meta_path: Path                     # meta.json
    meta: dict                          # parsed meta.json contents
    _artifacts: Optional[Tuple] = field(default=None, repr=False)

    def load(self):
        """Lazy-load CVAE model + preprocessor. Cached after first call."""
        if self._artifacts is None:
            from models.track_feature_predictor import load_cvae_artifact
            self._artifacts = load_cvae_artifact(str(self.model_path.parent))
        return self._artifacts  # (model, prep, meta)


class ModelRegistry:
    def __init__(self, base_dir: str = MODEL_ENGINEERING_DIR):
        self.base_dir = Path(base_dir)
        self.logit_models: Dict[str, LogitEntry] = {}
        self.cvae_models: Dict[str, CVAEEntry] = {}
        self.default_logit_version = LOGIT_MODEL_VERSION
        self._scan()

    def _scan(self):
        """Scan disk for all model artifacts and index them."""
        # --- Logit models ---
        for f in sorted(self.base_dir.glob("logit_model_*.joblib")):
            version = f.stem.replace("logit_model_", "")  # "v5"
            meta_path = self.base_dir / "metadata" / f"{f.stem}.json"
            features, test_metrics = [], {}
            if meta_path.exists():
                with open(meta_path) as mf:
                    meta = json.load(mf)
                    features = meta.get("features", [])
                    test_metrics = meta.get("test_metrics", {})

            self.logit_models[version] = LogitEntry(
                version=version,
                path=f,
                metadata_path=meta_path if meta_path.exists() else None,
                features=features,
                test_metrics=test_metrics,
            )

        # --- CVAE models ---
        # Current layout: features/ has model.pt, prep.pkl, meta.json
        # Future layout: features/cvae_v2/ for newer versions
        features_dir = self.base_dir / "features"
        if (features_dir / "model.pt").exists():
            with open(features_dir / "meta.json") as mf:
                meta = json.load(mf)
            version = meta.get("version", "v1")
            self.cvae_models[version] = CVAEEntry(
                version=version,
                model_path=features_dir / "model.pt",
                prep_path=features_dir / "prep.pkl",
                meta_path=features_dir / "meta.json",
                meta=meta,
            )

        # Scan for future versioned CVAE dirs (features/cvae_v2/, etc.)
        for d in sorted(self.base_dir.glob("features/cvae_*")):
            if d.is_dir() and (d / "model.pt").exists():
                with open(d / "meta.json") as mf:
                    meta = json.load(mf)
                version = meta.get("version", d.name.replace("cvae_", ""))
                self.cvae_models[version] = CVAEEntry(
                    version=version,
                    model_path=d / "model.pt",
                    prep_path=d / "prep.pkl",
                    meta_path=d / "meta.json",
                    meta=meta,
                )

    # --- Public API ---

    def get_logit(self, version: Optional[str] = None) -> LogitEntry:
        v = version or self.default_logit_version
        if v not in self.logit_models:
            raise ValueError(
                f"Logit model '{v}' not found. "
                f"Available: {list(self.logit_models.keys())}"
            )
        return self.logit_models[v]

    def get_cvae(self, version: Optional[str] = None) -> CVAEEntry:
        v = version or "v1"
        if v not in self.cvae_models:
            raise ValueError(
                f"CVAE model '{v}' not found. "
                f"Available: {list(self.cvae_models.keys())}"
            )
        return self.cvae_models[v]

    def list_logit_versions(self) -> list:
        return [
            {
                "version": e.version,
                "features": e.features,
                "n_features": len(e.features),
                "test_metrics": e.test_metrics,
                "is_default": e.version == self.default_logit_version,
            }
            for e in self.logit_models.values()
        ]

    def list_cvae_versions(self) -> list:
        return [
            {
                "version": e.version,
                "z_dim": e.meta.get("z_dim"),
                "n_c_cols": len(e.meta.get("c_cols", [])),
                "n_y_bin_cols": len(e.meta.get("y_bin_cols", [])),
            }
            for e in self.cvae_models.values()
        ]

    def set_default_logit(self, version: str):
        """Change the active default at runtime (no restart needed)."""
        if version not in self.logit_models:
            raise ValueError(f"Version '{version}' not available")
        self.default_logit_version = version
```

### 1.4 How Plug-and-Play Works

| Action | How |
|--------|-----|
| **Use default model** | `registry.get_logit().load()` → loads v5 (or whatever `LOGIT_MODEL_VERSION` is) |
| **Switch to v3 at runtime** | `registry.set_default_logit("v3")` — no restart, no config edit |
| **Request-level override** | `POST /api/v1/predict/connection { model_version: "v3" }` → `registry.get_logit("v3").load()` |
| **Add a new model v6** | Drop `logit_model_v6.joblib` + `metadata/logit_model_v6.json` into `feature_engineering/`, call `registry._scan()` or restart |
| **Add CVAE v2** | Create `feature_engineering/features/cvae_v2/` with `model.pt`, `prep.pkl`, `meta.json` |
| **Compare models** | `GET /api/v1/models` → returns all versions with their metrics side-by-side |

### 1.5 Integration into `app.py`

Replace the scattered `load_logit_model()` calls with a single registry instance:

```python
# app.py — at startup
from models.registry import ModelRegistry

registry = ModelRegistry()

# In endpoint handlers, replace:
#   logit_path = os.path.join(MODEL_ENGINEERING_DIR, f'logit_model_{LOGIT_MODEL_VERSION}.joblib')
#   pop_model = load_logit_model(f"logit_model_{LOGIT_MODEL_VERSION}", logit_path)
# With:
#   entry = registry.get_logit(req.model_version)   # or None for default
#   model = entry.load()
#   features = entry.features                        # knows its own feature list
```

**Key: each model version carries its own feature list** from the metadata JSON. v3 uses 18 features (with genre similarity), v5 uses 11. The registry returns the right feature list per version automatically — no hardcoded `LINK_PREDICTION_FEATURES` needed when using the registry.

### 1.6 New Endpoint: Model Inventory

```
GET /api/v1/models
```

```json
{
  "logit": [
    {
      "version": "v3",
      "n_features": 18,
      "features": ["similarity_prop_genre_rosamerica_spe", "cos_sim_src_dst", ...],
      "test_metrics": { "ROC AUC": 0.916, "F1 Score": 0.844, "Precision": 0.804, "Recall": 0.888 },
      "is_default": false
    },
    {
      "version": "v5",
      "n_features": 11,
      "features": ["cos_sim_src_dst", "dot_src_dst", ...],
      "test_metrics": { "ROC AUC": 0.916, "F1 Score": 0.843, "Precision": 0.803, "Recall": 0.888 },
      "is_default": true
    }
  ],
  "cvae": [
    {
      "version": "v1",
      "z_dim": 16,
      "n_conditioning_features": 7,
      "n_binary_outputs": 62
    }
  ],
  "active_default": { "logit": "v5", "cvae": "v1" }
}
```

### 1.7 New Endpoint: Switch Active Model

```
POST /api/v1/models/active
```
```json
{ "model_type": "logit", "version": "v3" }
```

Response: `{ "status": "ok", "active": "v3", "previous": "v5" }`

This is admin-only (requires auth, see §5). Changes the default for all subsequent requests until changed again or service restarts.

---

## 2. Endpoint Cleanup & Versioned API

### 2.1 Current State → Target State

| Current Endpoint | Current Path | New Versioned Path | Status |
|------------------|--------------|--------------------|--------|
| Predict link between two artists | `POST /ml/predict/artist-link` | `POST /api/v1/predict/connection` | Refactor |
| Predict neighbors for one artist | `POST /ml/predict/artist-neighbors` | `POST /api/v1/predict/neighbors` | Refactor |
| Generate synthetic tracks | `POST /ml/generate/tracks` | `POST /api/v1/generate/tracks` | Refactor (currently broken — uses `load_cvae_model` which is undefined) |
| Synthetic track similarity | `POST /ml/synthetic-tracks-similarity` | `POST /api/v1/similarity/tracks` | Refactor |
| Daily prediction | `POST /interlude/daily-prediction` | `POST /api/v1/predict/daily` | Refactor |
| **NEW**: Model inventory | — | `GET /api/v1/models` | Build |
| **NEW**: Switch active model | — | `POST /api/v1/models/active` | Build |
| **NEW**: Artist profile | — | `GET /api/v1/artist/{id}/profile` | Build |
| **NEW**: Batch prediction | — | `POST /api/v1/predict/batch` | Build |
| **NEW**: Health check | — | `GET /api/v1/health` | Build |

### 2.2 Backward Compatibility

The Go frontend (`machine_learning_handlers.go`) currently calls the old paths (`/ml/predict/artist-neighbors`, etc.) via `ML_SERVICE_URL`. Two options:

**Option A (Recommended)**: Keep old paths as thin aliases that forward to new handlers. Remove them in Phase 2.

```python
# Backward compat — old paths forward to new handlers
@app.post("/ml/predict/artist-link")
async def old_artist_link(req: ArtistLinkRequest):
    return await predict_connection_v1(req)

@app.post("/ml/predict/artist-neighbors")
async def old_artist_neighbors(req: ArtistNeighborRequest):
    return await predict_neighbors_v1(req)
```

**Option B**: Update the Go handlers to call new paths simultaneously. More work but cleaner.

### 2.3 Request Schema Changes

All v1 endpoints accept an optional `model_version` field. When omitted, the registry default is used.

```python
class PredictConnectionRequest(BaseModel):
    src_artist: str                              # MBID, Spotify ID, or name
    dst_artist: str
    model_version: Optional[str] = None          # "v3", "v5", etc.

class PredictNeighborsRequest(BaseModel):
    artist: str                                  # MBID, Spotify ID, or name
    limit: int = Field(default=25, le=100)
    min_probability: Optional[float] = None      # filter threshold
    model_version: Optional[str] = None

class PredictBatchRequest(BaseModel):
    pairs: List[dict]                            # [{"src": "...", "dst": "..."}, ...]
    model_version: Optional[str] = None
```

### 2.4 Response Schema Additions

Every response includes model metadata so the consumer knows what produced the result:

```python
class PredictionMeta(BaseModel):
    model_type: str              # "logit"
    model_version: str           # "v5"
    n_features: int              # 11
    latency_ms: float
    cache_hit: bool              # true if from prediction_connections table

class PredictConnectionResponse(BaseModel):
    src_artist: str
    dst_artist: str
    probability: float
    features_used: dict          # { "cos_sim_src_dst": 0.87, ... }
    meta: PredictionMeta
```

### 2.5 Artist Profile Endpoint

```
GET /api/v1/artist/{id}/profile
```

Combines data from multiple tables into a single response:

```python
# Implementation sketch
@app.get("/api/v1/artist/{artist_id}/profile")
def get_artist_profile(artist_id: str):
    """
    Sources:
    - artist table                → name, gid (MBID)
    - artist_mbid_spotify         → spotify_id
    - lastfm_artist_stats         → popularity score
    - artist_genre_proportions    → genre distribution (rosamerica, dortmund, etc.)
    - artist_embeddings_n2v       → embedding vector (128-dim, summarized)
    - artist_collab               → collaboration count, top collaborators
    - prediction_connections      → predicted connection count
    """
    # Single query joining all tables, or parallel queries
    # Return consolidated profile
```

Response:
```json
{
  "name": "Kendrick Lamar",
  "mbid": "381086ea-f511-4aba-bdf9-71c753dc5077",
  "spotify_id": "2YZyLoL8N0Wb9xBt1NhZWg",
  "popularity": 0.94,
  "genre_distribution": {
    "rosamerica": { "hip": 0.72, "rhy": 0.15, "pop": 0.08, "roc": 0.05 },
    "dortmund": { "raphiphop": 0.78, "pop": 0.12, "funksoulrnb": 0.10 }
  },
  "collab_count": 47,
  "top_collaborators": ["SZA", "Baby Keem", "Jay Rock"],
  "prediction_count": 1250,
  "embedding_summary": { "magnitude": 12.4, "cluster": "hip-hop-core" }
}
```

### 2.6 Health Check Endpoint

```python
@app.get("/api/v1/health")
def health():
    """Returns service status, loaded models, and DB connectivity."""
    return {
        "status": "ok",
        "models_loaded": {
            "logit": registry.list_logit_versions(),
            "cvae": registry.list_cvae_versions(),
        },
        "default_logit": registry.default_logit_version,
        "db_connected": _check_db(),
        "uptime_seconds": time.time() - APP_START_TIME,
    }
```

---

## 3. Model Improvements (Strategy §4.2)

These improvements are implemented as **new model versions** that slot into the registry. Existing models v1–v5 remain untouched.

### 3.1 Priority: High

#### 3.1.1 Add Era/Decade Features to Link Predictor → v6

**Problem**: Model predicts cross-era collaborations (Frank Sinatra ↔ Dua Lipa) because it has no temporal awareness.

**Implementation**:

1. **New feature columns**: `era_src`, `era_dst`, `era_diff`, `era_overlap`
   - Source: MusicBrainz `artist.begin_date_year` and `artist.end_date_year`
   - `era_diff = abs(midpoint_src - midpoint_dst)` in decades
   - `era_overlap = 1.0` if active periods overlap, `0.0` otherwise

2. **Feature pipeline change** (`features/build_features.py`):
   - Add `build_era_features(src_id, dst_id)` function
   - Called from `build_feature_row()` — appends era columns to feature dict

3. **Training**:
   - Retrain logit model with existing features + era features
   - Save as `logit_model_v6.joblib` + `metadata/logit_model_v6.json`
   - **Do not overwrite v5** — both coexist in the registry

4. **Validation**:
   - Compare v6 vs v5 on held-out test set
   - Specifically measure cross-era false positive rate
   - If v6 is better, switch default: `registry.set_default_logit("v6")`
   - If worse, keep v5 as default — v6 still available for experimentation

```sql
-- Query to get era data (add to database.py)
SELECT id,
       begin_date_year,
       end_date_year,
       COALESCE(end_date_year, EXTRACT(YEAR FROM NOW())) AS active_end
FROM artist
WHERE id = ANY(%s::int[]);
```

#### 3.1.2 Add Continuous CVAE Targets → cvae_v2

**Problem**: All 62 CVAE outputs are binary. No continuous features like energy, valence, tempo.

**Implementation**:

1. **New Y_CONT_COLS**: Pull from Spotify audio features or AcousticBrainz lowlevel
   - Candidates: `energy`, `valence`, `tempo_bpm`, `loudness_db`, `speechiness`
   - Source: `high_level_track_audio_features` or Spotify API batch fetch

2. **CVAE architecture change** (`models/track_feature_predictor.py`):
   - Decoder already supports continuous outputs (MSE loss path exists)
   - Just need non-empty `Y_CONT_COLS` in the config

3. **Training**:
   - New config at `config/cvae_config_v2.py` with populated `Y_CONT_COLS`
   - Train and save to `feature_engineering/features/cvae_v2/`
   - Structure: `model.pt`, `prep.pkl`, `meta.json` (with `"version": "v2"`)

4. **Registry integration**:
   - Auto-discovered by `ModelRegistry._scan()` (glob for `features/cvae_*`)
   - Accessible via `registry.get_cvae("v2")`

#### 3.1.3 Stratified Negative Sampling → v7

**Problem**: Random negative sampling over-represents popular artists in negatives too, hurting calibration.

**Implementation**:

1. In `models/link_predictor.py`, modify the negative pair generation:
   - Bin artists by genre cluster (rosamerica primary genre)
   - Sample negatives proportionally from each genre bin
   - Ensure cross-genre negatives are included

2. Retrain as v7 with same features as v5 (or v6 if era features help)
3. Compare calibration curves: v7 vs v5

### 3.2 Priority: Medium

#### 3.2.1 Artist Type Features → v8

Add `artist_type` (person, group, orchestra, choir, other) from MusicBrainz `artist.type` column.

```sql
SELECT a.id, at.name AS artist_type
FROM artist a
LEFT JOIN artist_type at ON a.type = at.id
WHERE a.id = ANY(%s::int[]);
```

One-hot encode and add to feature set. Solo artist + band has different collaboration dynamics than band + band.

#### 3.2.2 A/B Test PU Learning vs Standard Logistic Regression

Train a standard sklearn `LogisticRegression` (no PU wrapper) as a separate version. Compare on the same test set. This validates whether the PU learning wrapper (`ElkanotoPuClassifier`) is actually helping.

- Train as `logit_model_v_standard.joblib`
- Registry treats it like any other version
- Compare metrics side-by-side via `GET /api/v1/models`

#### 3.2.3 Per-Genre Models

Train separate logit models per genre cluster:
- `logit_model_v5_rock.joblib`
- `logit_model_v5_hiphop.joblib`
- etc.

Registry extension: `registry.get_logit("v5", genre="rock")`. Falls back to general model if genre-specific not available.

### 3.3 Priority: Low (Phase 2+)

- GNN-based link predictor (GraphSAGE) — new model type in registry
- Online learning from prediction feedback — requires feedback loop from §7

### 3.4 Model Version Comparison Workflow

```
You train v6 with era features:
  1. Drop logit_model_v6.joblib into feature_engineering/
  2. Drop logit_model_v6.json into feature_engineering/metadata/
  3. Call POST /api/v1/models/active { "model_type": "logit", "version": "v6" }
     OR just test with: POST /api/v1/predict/connection { ..., "model_version": "v6" }
  4. Compare: GET /api/v1/models → see v5 and v6 metrics side by side
  5. If v6 is better, set as default. If not, keep v5.
  6. v3 is always there too — switch back anytime.
```

---

## 4. Metrics & Monitoring (Strategy §4.3)

### 4.1 Model Quality Metrics

These are computed per model version and stored in the database for trending.

#### 4.1.1 Precision@k

```python
# metrics/model_metrics.py

def precision_at_k(model_version: str, k: int = 10) -> float:
    """
    For a sample of artists, predict top-k neighbors.
    Check how many of the top-k actually have real collaborations
    that the model didn't see during training.

    Uses held-out test edges from training split.
    """
    # 1. Load held-out positive edges (not in training data)
    # 2. For each src in test set, predict top-k neighbors
    # 3. precision = |predicted ∩ actual| / k
    # 4. Average across all test sources
```

#### 4.1.2 NDCG (Normalized Discounted Cumulative Gain)

```python
def ndcg_at_k(model_version: str, k: int = 25) -> float:
    """
    Measures ranking quality: are the highest-probability predictions
    actually the most likely to be real collaborations?

    Uses scipy.stats.kendalltau or sklearn.metrics.ndcg_score.
    """
```

#### 4.1.3 Calibration Curve

```python
def calibration_data(model_version: str, n_bins: int = 10) -> dict:
    """
    Returns {predicted_prob_bin: actual_collab_rate} pairs.

    Example output:
    { "0.3-0.4": 0.12, "0.4-0.5": 0.28, "0.5-0.6": 0.41, ... }

    Perfect calibration: predicted prob ≈ actual rate.
    """
```

#### 4.1.4 Genre Diversity Score

```python
def genre_diversity(model_version: str, sample_size: int = 1000) -> float:
    """
    For a random sample of predictions, measure the genre entropy
    of predicted neighbors. Low diversity = popularity collapse
    (model keeps predicting the same popular artists).

    Returns: Shannon entropy of genre distribution across predictions.
    Higher = more diverse = better.
    """
```

### 4.2 System Health Metrics

Implemented via FastAPI middleware that logs every request.

```python
# middleware/metrics.py

import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Logs per-request metrics to the api_usage_log table.
    Tracks: endpoint, method, status_code, latency_ms, model_version used.
    """
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        latency_ms = (time.time() - start) * 1000

        # Log to database (async, non-blocking)
        await log_request_metrics(
            endpoint=request.url.path,
            method=request.method,
            status_code=response.status_code,
            latency_ms=latency_ms,
            user_id=getattr(request.state, "user_id", None),
        )

        # Add timing header
        response.headers["X-Latency-Ms"] = f"{latency_ms:.1f}"
        return response
```

**Metrics tracked per endpoint**:

| Metric | How | Alert Threshold |
|--------|-----|-----------------|
| P50 latency | Median of `latency_ms` over last hour | > 2s for predict/connection |
| P95 latency | 95th percentile | > 10s for predict/neighbors |
| P99 latency | 99th percentile | > 30s |
| Error rate | `status_code >= 500` / total | > 5% |
| Cache hit rate | fast path / (fast + slow) in predict/neighbors | < 60% (means DB cache is stale) |
| DB query time | Instrumented in `database.py` | P95 > 500ms |

### 4.3 Business Metrics

Computed from `api_usage_log` and `api_users` tables:

| Metric | SQL / Logic |
|--------|-------------|
| API calls per user per day | `SELECT user_id, DATE(created_at), COUNT(*) FROM api_usage_log GROUP BY 1,2` |
| Playlist creation rate | Count of `/api/v1/generate/playlist` calls / total users |
| Dataset export volume | `SELECT SUM(row_count) FROM dataset_exports WHERE created_at > NOW() - INTERVAL '30 days'` |
| DAU / MAU ratio | Distinct `user_id` in api_usage_log per day vs per month |
| Model version adoption | `SELECT request_params->>'model_version', COUNT(*) FROM api_usage_log GROUP BY 1` |

### 4.4 Metrics Dashboard Endpoint

```
GET /api/v1/metrics/summary
```

Returns aggregated metrics for the last 24h / 7d / 30d. Admin-only.

```json
{
  "period": "24h",
  "requests_total": 12450,
  "latency": { "p50": 145, "p95": 890, "p99": 2340 },
  "error_rate": 0.02,
  "cache_hit_rate": 0.73,
  "top_endpoints": [
    { "path": "/api/v1/predict/neighbors", "count": 8200 },
    { "path": "/api/v1/predict/connection", "count": 3100 }
  ],
  "model_usage": { "v5": 11200, "v3": 1250 },
  "unique_users": 45
}
```

---

## 5. Auth Middleware & Rate Limiting

### 5.1 API Key Authentication

```python
# middleware/auth.py

from fastapi import Request, HTTPException
from fastapi.security import APIKeyHeader
import hashlib

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def authenticate(request: Request):
    """
    Extract API key from header, hash it, look up in api_users.
    Sets request.state.user_id and request.state.tier.

    Exempt paths: /api/v1/health, /docs, /openapi.json
    """
    key = request.headers.get("X-API-Key")
    if not key:
        raise HTTPException(status_code=401, detail="Missing API key")

    key_hash = hashlib.sha256(key.encode()).hexdigest()

    # Look up user by key hash
    user = await get_user_by_key_hash(key_hash)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")

    request.state.user_id = user["user_id"]
    request.state.tier = user["tier"]
    request.state.rate_limit = user["rate_limit_per_hour"]
```

### 5.2 Rate Limiting

```python
# middleware/rate_limit.py

from collections import defaultdict
import time

# In-memory sliding window (upgrade to Redis for multi-instance)
_windows: dict = defaultdict(list)

async def check_rate_limit(request: Request):
    """
    Sliding window rate limiter.
    Checks request.state.rate_limit (set by auth middleware).
    """
    user_id = request.state.user_id
    limit = request.state.rate_limit
    now = time.time()
    window = 3600  # 1 hour

    # Clean old entries
    _windows[user_id] = [t for t in _windows[user_id] if now - t < window]

    if len(_windows[user_id]) >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({limit}/hour)",
            headers={"Retry-After": "60"}
        )

    _windows[user_id].append(now)
```

### 5.3 Tier Definitions

| Tier | Rate Limit | Batch Size | Export | Model Selection |
|------|-----------|------------|--------|----------------|
| `free` | 100/hour | N/A | No | Default only |
| `researcher` | 1,000/hour | 1,000 pairs | 100k rows/month | Any version |
| `enterprise` | 10,000/hour | Unlimited | Unlimited | Any + custom training |
| `admin` | Unlimited | Unlimited | Unlimited | Full access + model switching |

### 5.4 Integration Order

```python
# app.py
app = FastAPI(...)

# 1. Metrics first (logs everything including auth failures)
app.add_middleware(MetricsMiddleware)

# 2. Auth + rate limit as dependencies on protected routes
from middleware.auth import authenticate
from middleware.rate_limit import check_rate_limit

# Public routes (no auth)
@app.get("/api/v1/health")
def health(): ...

# Protected routes
@app.post("/api/v1/predict/connection", dependencies=[Depends(authenticate), Depends(check_rate_limit)])
def predict_connection(req: PredictConnectionRequest): ...
```

---

## 6. Security Hardening

### 6.1 Credential Removal (Immediate — Do First)

**Current state** in `config/config.py`:

```python
# HARDCODED — MUST MOVE TO ENV VARS
LAST_FM_KEYS = {
    "api_key": "63b3374cc59f0f75f1d7959d4216ae49",    # line 16
    "secret": "7e6f2f2994602636c6cc454deca3719b",      # line 17
}
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "9ce2d15fb4114cceb56097c7fa53e734")     # line 22
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "6a94edbec2cf45a290b4f3d53762c403")  # line 23
DB_URL = os.getenv("PG_DSN", "postgres://postgres:baseball162162@localhost:5432/...")       # line 9
```

**Fix**: Remove all hardcoded defaults. Use env vars only. Fail loudly if missing.

```python
# config/config.py — AFTER fix
DB_URL = os.environ["PG_DSN"]  # no default — must be set

LAST_FM_API_KEY = os.environ.get("LASTFM_API_KEY", "")
LAST_FM_SECRET = os.environ.get("LASTFM_SECRET", "")

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
```

Add to `docker-compose.yml` ml service environment (or `.env.docker`):

```yaml
environment:
  PG_DSN: ...
  LASTFM_API_KEY: ${LASTFM_API_KEY}
  LASTFM_SECRET: ${LASTFM_SECRET}
  SPOTIFY_CLIENT_ID: ${SPOTIFY_CLIENT_ID}
  SPOTIFY_CLIENT_SECRET: ${SPOTIFY_CLIENT_SECRET}
```

### 6.2 .gitignore Update

Ensure these patterns are present:

```
# Secrets
.env
.env.*
*.env

# Model artifacts (large binaries)
*.joblib
*.pt
*.pkl
*.parquet

# Python
__pycache__/
*.pyc
.venv/
venv/

# Data
acousticbrainz/data/
*.csv
*.npy
*.edgelist
```

### 6.3 Input Validation

Add Pydantic validators to all request schemas:

```python
from pydantic import BaseModel, Field, field_validator
import re

UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')

class PredictConnectionRequest(BaseModel):
    src_artist: str
    dst_artist: str
    model_version: Optional[str] = None

    @field_validator("src_artist", "dst_artist")
    @classmethod
    def validate_artist_id(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Artist ID cannot be empty")
        if len(v) > 200:
            raise ValueError("Artist ID too long")
        # Allow MBID (UUID), integer ID, or name
        return v

    @field_validator("model_version")
    @classmethod
    def validate_model_version(cls, v):
        if v is not None and not re.match(r'^v\d+$', v):
            raise ValueError("Model version must be 'vN' format (e.g., 'v5')")
        return v
```

---

## 7. Database Migrations

### 7.1 New Tables for Phase 1

Run these migrations against `musicbrainz_db`:

```sql
-- ---------------------------------------------------------------
-- 1. API Users & Access Control
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    org_name TEXT,
    tier TEXT NOT NULL DEFAULT 'free'
        CHECK (tier IN ('free', 'researcher', 'enterprise', 'admin')),
    api_key_hash TEXT UNIQUE NOT NULL,
    rate_limit_per_hour INT NOT NULL DEFAULT 100,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_active TIMESTAMPTZ
);

-- ---------------------------------------------------------------
-- 2. API Usage Log (for metrics §4)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_usage_log (
    log_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id UUID REFERENCES api_users(user_id),
    endpoint TEXT NOT NULL,
    method TEXT NOT NULL,
    status_code INT,
    latency_ms FLOAT,
    model_version TEXT,
    request_params JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_usage_user_date
    ON api_usage_log(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_api_usage_endpoint
    ON api_usage_log(endpoint, created_at);

-- ---------------------------------------------------------------
-- 3. Model Quality Metrics Log
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS model_metrics_log (
    metric_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_type TEXT NOT NULL,           -- 'logit', 'cvae'
    model_version TEXT NOT NULL,        -- 'v5', 'v3', etc.
    metric_name TEXT NOT NULL,          -- 'precision_at_10', 'ndcg_at_25', etc.
    metric_value FLOAT NOT NULL,
    sample_size INT,
    computed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_model_metrics_version
    ON model_metrics_log(model_type, model_version, computed_at);

-- ---------------------------------------------------------------
-- 4. Prediction Feedback (for future model improvement)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prediction_feedback (
    feedback_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id UUID REFERENCES api_users(user_id),
    prediction_src INT NOT NULL,
    prediction_dst INT NOT NULL,
    model_version TEXT,
    rating INT CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 7.2 Migration Script Location

Create `machinelearning/migrations/001_phase1_tables.sql` with the above. Run via:

```bash
psql $PG_DSN -f migrations/001_phase1_tables.sql
```

Or add a startup check in `app.py`:

```python
@app.on_event("startup")
async def run_migrations():
    """Idempotent table creation on service start."""
    conn = get_pg_conn()
    with open("migrations/001_phase1_tables.sql") as f:
        conn.cursor().execute(f.read())
    conn.commit()
    conn.close()
```

---

## 8. Deployment & TLS

### 8.1 Docker Compose Changes

```yaml
# Add nginx reverse proxy for TLS termination
services:
  nginx:
    image: nginx:alpine
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf
      - ./nginx/certs:/etc/nginx/certs
    depends_on:
      - api
      - ml

  api:
    # ... existing config unchanged ...

  ml:
    # ... existing config unchanged ...
    # Add health check
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### 8.2 OpenAPI Docs

FastAPI auto-generates these. Ensure they're accessible:

- **Internal**: `http://ml:8000/docs` (Swagger UI)
- **External**: `https://yourdomain.com/api/docs` (proxied via nginx)
- **JSON spec**: `https://yourdomain.com/api/openapi.json`

Customize in `app.py`:

```python
app = FastAPI(
    title="Interlude Synthetic Collaboration API",
    version="1.0.0",
    description="Predict artist collaborations and generate synthetic track features.",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
```

---

## 9. Final Output & Scale Targets

### 9.1 What Phase 1 Delivers

| Deliverable | Detail |
|-------------|--------|
| **Versioned API** | All endpoints under `/api/v1/` with backward compat aliases |
| **Model Registry** | Plug-and-play: switch between v1/v2/v3/v5 (and future versions) at runtime via API or config |
| **Auth + Rate Limiting** | API key auth, tier-based rate limits, usage logging |
| **Metrics Pipeline** | Per-request latency/error logging, model quality metrics (P@k, NDCG, calibration, diversity) |
| **Artist Profile** | New endpoint consolidating all artist data |
| **Health Check** | Service status, loaded models, DB connectivity |
| **Security** | Credentials moved to env vars, input validation, .gitignore cleanup |
| **OpenAPI Docs** | Auto-generated, publicly accessible |

### 9.2 Scale Targets (End of Phase 1)

| Metric | Target |
|--------|--------|
| Predict/connection latency (cached) | < 200ms P95 |
| Predict/connection latency (uncached) | < 5s P95 |
| Predict/neighbors latency (cached) | < 500ms P95 |
| Predict/neighbors latency (uncached) | < 30s P95 |
| Concurrent users | 50 simultaneous |
| Model switch time | < 1s (lazy load from disk) |
| Uptime target | 99.5% |
| DB connection pool | 10 connections (pgBouncer in Phase 2) |

### 9.3 Implementation Order

```
Week 1:
  [1] Security hardening — remove hardcoded creds from config.py
  [2] Create .gitignore with proper patterns
  [3] Build ModelRegistry class (models/registry.py)
  [4] Wire registry into app.py, replace hardcoded model loading
  [5] Add GET /api/v1/models endpoint
  [6] Add GET /api/v1/health endpoint

Week 2:
  [7] Refactor existing endpoints to /api/v1/ paths
  [8] Add backward compat aliases for old paths
  [9] Implement new request/response schemas with model metadata
  [10] Build GET /api/v1/artist/{id}/profile endpoint
  [11] Build POST /api/v1/predict/batch endpoint

Week 3:
  [12] Database migrations (api_users, api_usage_log, model_metrics_log)
  [13] Build auth middleware (API key validation)
  [14] Build rate limiting middleware
  [15] Build metrics middleware (request logging)
  [16] Build GET /api/v1/metrics/summary endpoint

Week 4:
  [17] Implement model quality metrics (P@k, NDCG, calibration, diversity)
  [18] Add nginx reverse proxy + TLS to docker-compose
  [19] Customize OpenAPI docs
  [20] End-to-end testing: auth → predict → metrics logged
  [21] Begin training v6 (era features) as first registry test
```

### 9.4 What Changes vs What Doesn't

| Changes | Does NOT Change |
|---------|----------------|
| `app.py` — new endpoints, registry integration, middleware | `models/link_predictor.py` — existing model code |
| `config/config.py` — remove hardcoded creds | `models/track_feature_predictor.py` — CVAE code |
| New files: `models/registry.py`, `middleware/auth.py`, `middleware/rate_limit.py`, `middleware/metrics.py` | `features/build_features.py` — feature engineering |
| New dir: `migrations/` | `features/pipeline_links.py` — pipeline |
| `docker-compose.yml` — add nginx, health checks | `utils/database.py` — DB utilities |
| `.gitignore` — proper patterns | Existing `.joblib`, `.pt`, `.pkl` files on disk |
| New tables in PostgreSQL | Existing tables (artist, prediction_connections, etc.) |

---

## Appendix A: File Map

```
machinelearning/
├── app.py                              # ← MODIFY: registry, new endpoints, middleware
├── config/
│   ├── config.py                       # ← MODIFY: remove hardcoded creds
│   └── cvae_config.py                  #   (no changes)
├── features/
│   ├── build_features.py               #   (no changes in Phase 1; v6 era features in §3.1.1)
│   └── pipeline_links.py              #   (no changes)
├── models/
│   ├── link_predictor.py              #   (no changes)
│   ├── track_feature_predictor.py     #   (no changes)
│   ├── track_similarity.py            #   (no changes)
│   ├── artist_similarity.py           #   (no changes)
│   ├── one_time_link_predictor.py     #   (no changes)
│   ├── return_link_embeddings.py      #   (no changes)
│   └── registry.py                     # ← NEW: plug-and-play model registry
├── middleware/                          # ← NEW DIRECTORY
│   ├── __init__.py
│   ├── auth.py                         # ← NEW: API key auth
│   ├── rate_limit.py                   # ← NEW: tier-based rate limiting
│   └── metrics.py                      # ← NEW: request metrics logging
├── metrics/                            # ← NEW DIRECTORY
│   └── model_metrics.py               # ← NEW: P@k, NDCG, calibration, diversity
├── migrations/                         # ← NEW DIRECTORY
│   └── 001_phase1_tables.sql          # ← NEW: api_users, api_usage_log, etc.
├── utils/
│   ├── database.py                    #   (no changes)
│   └── metrics.py                     #   (no changes)
├── feature_engineering/                #   (no changes — models live here untouched)
│   ├── logit_model_v1.joblib
│   ├── logit_model_v2.joblib
│   ├── logit_model_v3.joblib
│   ├── logit_model_v5.joblib
│   ├── features/                      #   CVAE v1 artifacts
│   └── metadata/                      #   model metadata JSONs
├── Dockerfile                         #   (no changes)
└── requirements.txt                   #   (no changes)
```
