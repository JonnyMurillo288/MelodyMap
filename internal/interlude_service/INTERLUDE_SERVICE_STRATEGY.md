# Interlude Service: Output Strategy & Go-to-Market Plan

## 1. What Exists Today (Current State)

### 1.1 Models Built
| Model | Type | Purpose | Performance |
|-------|------|---------|-------------|
| **Link Predictor** (v5) | Logistic Regression + PU Learning (ElkanotoPu) | Predicts probability two artists would collaborate | ROC AUC: 0.92, F1: 0.84 |
| **Hop Predictor** (Dont use)| ElasticNet Regression | Predicts shortest-path distance between artists | MAE: 0.76, Accuracy +/-1 hop: 94% |
| **CVAE**  | Conditional Variational Autoencoder (PyTorch) | Generates synthetic track features (genre, mood, timbre, rhythm, danceability) conditioned on artist-pair context | Loss-based + generative validation (diversity, correlation) |
| **Track Similarity** | Aitchison Distance | Finds real tracks most similar to synthetic tracks by genre distribution | Exact (distance metric) |
| **Artist Similarity** | Aitchison Distance on genre proportions | Calculates genre-based similarity between artist pairs | Exact (distance metric) |

### 1.2 Feature Pipeline
- **Node2Vec embeddings** (128-dim, 20 walks, walk length 20) stored in `artist_embeddings_n2v`
- **Feature groups**: Geometry (cosine sim, L2, dot product), Popularity (LastFM), One-hop (neighbor reachability), Two-hop (shared neighbors, Jaccard, Adamic-Adar, preferential attachment), Genre similarity (Rosamerica classification)
- **CVAE conditioning vector (C)**: cos_sim, l2_dist, popularity_src/dst, mean_topk_cos, shared_neighbors
- **CVAE output (Y)**: 62 binary features covering danceability, gender, 4 genre taxonomies, rhythm, mood, timbre, tonality, voice/instrumental

### 1.3 Existing API Endpoints (FastAPI on port 8000)
| Endpoint | Method | Status | Description |
|----------|--------|--------|-------------|
| `/ml/predict/artist-link` | POST | Working | Predict collaboration probability between two specific artists |
| `/ml/predict/artist-neighbors` | POST | Working | Get top-k predicted neighbors for one artist (fast path: DB cache, slow path: ML pipeline) |
| `/ml/generate/tracks` | POST | Partial | Generate synthetic track features for an artist pair |
| `/ml/synthetic-tracks-similarity` | POST | Working | Find real tracks similar to synthetic tracks via Aitchison distance |
| `/interlude/daily-prediction` | POST | Working | Daily genre-based random artist prediction for Spotle |

### 1.4 Existing Database Tables
| Table | Purpose |
|-------|---------|
| `artist` | MusicBrainz artist metadata (id, gid/MBID, name) |
| `artist_collab` | Real collaboration edges (artist_id, neighbor_artist_id, recording_id) |
| `artist_embeddings_n2v` | Node2Vec embeddings per artist |
| `lastfm_artist_stats` | Popularity scores from Last.fm |
| `artist_genre_proportions` | Per-artist genre distribution proportions (4 taxonomies) |
| `high_level_track_audio_features` | AcousticBrainz track-level features |
| `paths` | Pre-computed shortest path hop counts |
| `predict_connection_model` | Model metadata (model_id, date, description) |
| `prediction_connections` | Predicted links (src, dst, prob, model_id) |
| `synthetic_tracks` | Generated synthetic tracks (track_id, src_artist_id, dst_artist_id, prediction_id) |
| `synthetic_tracks_high_level_features` | CVAE-generated features per synthetic track |
| `synthetic_track_model_versions` | Model version tracking per synthetic track |
| `spotify_genres` | Spotify genre tags per artist |
| `artist_mbid_spotify` | MBID to Spotify ID mapping |

### 1.5 Known Issues
- Model is heavily biased toward popular artists (MODEL_DOCUMENTATION.md notes this)
- No time-period or era filtering for collaboration prediction
- `torch==2.10.0` was broken in Dockerfile (fixed)
- `tensorboard` was commented out in requirements (fixed)
- Duplicate `get_id_from_mbid` functions across files
- No production monitoring or data drift detection

---

## 2. Proposed Output Service Architecture

### 2.1 Target User Personas

**Primary: Technical Music Researchers & Developers**
- AI/ML researchers, music analytics engineers, data scientists
- Want: Raw data, API access, parameter tuning, bulk exports
- Value: Synthetic connection probabilities, track feature vectors, embedding access, model versioning

**Secondary: Non-Technical Music Industry Professionals**
- Record labels, producers, marketers, distribution companies
- Want: Dashboards, playlist generation, trend discovery, artist-pairing recommendations
- Value: "What if" scenarios, popular potential collaborations, genre-crossing opportunities

### 2.2 Endpoint Design

#### Tier 1: Core Prediction Endpoints (Existing, to refine)

```
POST /api/v1/predict/connection
```
**Input**: `{ src_artist: str, dst_artist: str, model_version?: str }`
**Output**: `{ probability: float, confidence_interval: [float, float], features_used: dict, model_version: str }`
**Notes**: Accepts MBID, Spotify ID, or artist name. Returns cached if available.

```
POST /api/v1/predict/neighbors
```
**Input**: `{ artist: str, limit: int, min_probability?: float, genre_filter?: str[], era_filter?: str }`
**Output**: `{ artist_name: str, neighbors: [{ name, probability, genre_overlap, shared_neighbors }] }`
**Notes**: The primary discovery endpoint. Supports filtering by genre and era.

```
POST /api/v1/predict/batch
```
**Input**: `{ pairs: [{ src, dst }], model_version?: str }`
**Output**: `{ results: [{ src, dst, probability }] }`
**Notes**: Bulk prediction for API customers. Rate-limited per tier.

#### Tier 2: Synthetic Track Endpoints (Existing, to refine)

```
POST /api/v1/generate/tracks
```
**Input**: `{ src_artist: str, dst_artist: str, num_tracks: int, constraints?: { genre_bias?: str, mood?: str, min_danceability?: float } }`
**Output**: `{ tracks: [{ track_id, features: { genre_probs, mood, danceability, timbre, ... }, predicted_popularity }] }`
**Notes**: CVAE generation with optional constraint steering via conditioning vector manipulation.

```
POST /api/v1/generate/playlist
```
**Input**: `{ synthetic_track_ids: [int], num_similar: int, spotify_create?: bool }`
**Output**: `{ playlist: [{ track_name, artist_name, similarity_score, spotify_uri? }] }`
**Notes**: Maps synthetic tracks to real tracks via Aitchison similarity, optionally creates Spotify playlist.

#### Tier 3: New Endpoints to Build

```
GET /api/v1/artist/{id}/profile
```
**Output**: `{ name, mbid, spotify_id, popularity, genre_distribution, embedding_summary, collab_count, top_collabs }`
**Notes**: Comprehensive artist profile combining all data sources. Foundation for both user types.

```
POST /api/v1/explore/what-if
```
**Input**: `{ artists: [str], scenario: { genre_target?: str, popularity_range?: [int, int], mood_target?: str } }`
**Output**: `{ scenarios: [{ pair, probability, synthetic_tracks, similar_real_tracks }] }`
**Notes**: The "what would happen if X and Y collaborated?" endpoint. Key differentiator for secondary users.

```
GET /api/v1/trends/daily
```
**Output**: `{ date, featured_connections: [{ src, dst, probability, genre, synthetic_playlist }] }`
**Notes**: Pre-computed daily content for engagement (Spotle integration). Cached.

```
GET /api/v1/dataset/export
```
**Input**: Query params for filtering (genre, probability threshold, date range, limit)
**Output**: CSV/Parquet download of prediction_connections with features
**Notes**: Licensed dataset endpoint for primary users. Metered.

```
POST /api/v1/model/feedback
```
**Input**: `{ prediction_id, rating: int, comment?: str }`
**Notes**: Collect user feedback on prediction quality for model improvement.

### 2.3 Database Schema (New Tables)

```sql
-- ---------------------------------------------------------------
-- API Users & Access Control
-- ---------------------------------------------------------------
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

-- ---------------------------------------------------------------
-- Daily Predictions Cache (for /trends/daily and Spotle)
-- ---------------------------------------------------------------
CREATE TABLE daily_predictions (
    prediction_date DATE NOT NULL,
    genre TEXT NOT NULL,
    src_artist_id INT NOT NULL,
    src_artist_name TEXT,
    dst_artist_id INT NOT NULL,
    dst_artist_name TEXT,
    probability FLOAT,
    synthetic_track_ids INT[],
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (prediction_date, genre, src_artist_id, dst_artist_id)
);

-- ---------------------------------------------------------------
-- User Feedback for Model Improvement
-- ---------------------------------------------------------------
CREATE TABLE prediction_feedback (
    feedback_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id UUID REFERENCES api_users(user_id),
    prediction_src INT NOT NULL,
    prediction_dst INT NOT NULL,
    model_id INT,
    rating INT CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------
-- Dataset Export Requests (audit trail)
-- ---------------------------------------------------------------
CREATE TABLE dataset_exports (
    export_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES api_users(user_id),
    filters JSONB,
    row_count INT,
    file_format TEXT DEFAULT 'csv',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------
-- What-If Scenario Cache
-- ---------------------------------------------------------------
CREATE TABLE scenario_cache (
    cache_key TEXT PRIMARY KEY,  -- hash of (src, dst, constraints)
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '7 days'
);
```

### 2.4 Caching Strategy

| Data | Cache Location | TTL | Invalidation |
|------|---------------|-----|--------------|
| Prediction connections (per model) | `prediction_connections` table | Until model retrain | ON model version change, mark stale |
| Synthetic tracks | `synthetic_tracks` + `synthetic_tracks_high_level_features` | Permanent (versioned) | Never deleted, versioned by model |
| Daily predictions | `daily_predictions` table | 24 hours | Pre-computed via scheduler at midnight EST |
| Artist profiles | Redis/in-memory | 1 hour | On artist data update |
| What-if scenarios | `scenario_cache` table | 7 days | TTL-based expiry |
| Embedding lookups | In-memory (Go) | Process lifetime | On server restart |

---

## 3. User Display & UX

### 3.1 Primary User (Technical / API)

**Interface**: REST API + Swagger/OpenAPI docs at `/docs`

**Key UX Elements**:
- Interactive API explorer (already via FastAPI `/docs`)
- Webhook support for long-running batch predictions
- Downloadable datasets (CSV/Parquet) with filtering
- Model version selection in every request
- Detailed response metadata (latency, model version, feature weights used)

**Dashboard**:
- Model performance metrics over time
- Prediction distribution histograms
- Feature importance visualization
- Data drift monitoring charts

### 3.2 Secondary User (Non-Technical / Web)

**Interface**: Web application at `/ml` (existing template, to enhance)

**Current State** (from `ml_page.html`):
- Table 1: Artist and their real connections
- Table 2: Non-connected artists with collaboration scores (synthetic predictions)
- Saved connections panel for Spotify playlist creation

**Enhancements Needed**:

1. **Artist Profile Card**: When selecting an artist, show a card with genre distribution (radar chart), popularity, collaboration count, top collaborators

2. **"What If" Composer**: Two artist search boxes + a "What would they create?" button. Shows:
   - Collaboration probability with confidence
   - Predicted track characteristics (genre radar, mood bar, danceability gauge)
   - List of similar real tracks that match the synthetic prediction

3. **Daily Discovery Page** (`/daily`):
   - Genre-filtered daily featured prediction
   - One-click Spotify playlist creation
   - Spotle game integration (guess the artist from the synthetic playlist)

4. **Trend Explorer**:
   - Filter by genre, popularity range, era
   - Sort by probability, genre diversity, surprise factor
   - Exportable results

---

## 4. Models, Metrics & Improvements

### 4.1 Current Model Limitations (from your MODEL_DOCUMENTATION.md)

1. **Popularity bias**: Model favors popular artists. Frank Sinatra gets matched with Dua Lipa, Kendrick Lamar
2. **No temporal awareness**: No era/time-period filtering
3. **Genre features weakly weighted**: Genre similarity coefficients are small (0.02-0.06) vs. graph features (2.3 for Jaccard)
4. **No continuous CVAE targets**: Y_CONT_COLS is empty; all 62 outputs are binary

### 4.2 Recommended Model Improvements

| Improvement | Priority | Impact | Effort |
|-------------|----------|--------|--------|
| Add era/decade features to link predictor | High | Reduces cross-era false positives | Medium |
| Add continuous CVAE targets (popularity, energy, valence from Spotify) | High | Richer synthetic tracks | Medium |
| Increase negative sampling diversity (stratify by genre, not just random) | High | Better calibration | Low |
| Add artist type features (solo, band, DJ, orchestra) | Medium | Better context | Low |
| Train separate models per genre cluster | Medium | Domain-specific accuracy | High |
| A/B test PU learning vs. standard logistic regression | Medium | Validate PU benefit | Low |
| Add GNN-based link predictor (GraphSAGE) | Low | Potential accuracy gain | High |
| Implement online learning for prediction feedback | Low | Model adapts to user signal | High |

### 4.3 Metrics to Track in Production

**Model Quality**:
- Precision@k for top-k neighbor predictions
- NDCG for ranking quality
- Calibration curve (predicted probability vs. actual collaboration rate)
- Genre diversity of predictions (to detect popularity collapse)

**System Health**:
- P50/P95/P99 latency per endpoint
- Cache hit rate (fast path vs. slow path ratio)
- Error rate by endpoint
- DB query timing

**Business Metrics**:
- API calls per user per day
- Playlist creation rate
- Dataset export volume
- User retention (daily active / monthly active)

---

## 5. Security

### 5.1 User & Account Security

| Concern | Implementation |
|---------|---------------|
| **Authentication** | API key (hashed, stored in `api_users`) for API access. OAuth2 (Spotify) for playlist features. |
| **Authorization** | Tier-based access (free/researcher/enterprise). Rate limits enforced per tier. |
| **Session management** | JWT tokens with short expiry (existing `SDS_TOKEN_SECRET`). Rotate Spotify refresh tokens. |
| **Account security** | Email verification on signup. API key rotation endpoint. Audit log of all API usage. |

### 5.2 Internal Data Protection

| Concern | Implementation |
|---------|---------------|
| **Credential management** | Move all secrets to environment variables (partially done). Remove hardcoded API keys from `config.py` (Last.fm key, Spotify client_id/secret are currently in source). Use a secrets manager (Vault, AWS SSM) in production. |
| **Database access** | Use connection pooling (pgBouncer). Read replicas for API queries. Write access only from pipeline jobs. |
| **Data at rest** | PostgreSQL TDE or filesystem encryption. Embeddings are not PII but are proprietary. |
| **Data in transit** | TLS everywhere. HTTPS termination at reverse proxy (nginx/Caddy). |

### 5.3 API Attack Prevention

| Attack Vector | Mitigation |
|---------------|------------|
| **Rate limiting** | Per-user hourly limits (100/1000/unlimited by tier). Burst protection. |
| **Scraping prevention** | Anti-scrape token system (already exists in `SDS_TOKEN_SECRET`). Fingerprinting repeated full-dataset queries. |
| **SQL injection** | Already using parameterized queries (`%s` params in psycopg2). Validate and sanitize all user inputs. |
| **Data exfiltration** | Limit export sizes per tier. Watermark exported datasets with user_id. Log all exports. |
| **DDoS** | Cloudflare or equivalent WAF. Response caching for read endpoints. |
| **Model inversion** | Don't expose raw embeddings via API. Return only derived features (probabilities, distances). |

### 5.4 Immediate Security Actions Required

1. **CRITICAL**: Remove hardcoded credentials from `config.py`:
   - Last.fm API key and secret (lines 14-19)
   - Spotify client_id and client_secret (lines 22-23)
   - PostgreSQL password in DB_URL default (line 9)
2. Add `.env` files to `.gitignore` (partially done, verify)
3. Rotate all exposed credentials immediately
4. Add input validation to all FastAPI endpoints (partially done via Pydantic, but string-based artist IDs need UUID/format validation)

---

## 6. Pricing & Business Model

### 6.1 Pricing Tiers

| Tier | Price | Rate Limit | Features |
|------|-------|------------|----------|
| **Free** | $0/month | 100 requests/hour | Single artist predictions, 10 neighbors max, no batch, no export |
| **Researcher** | $49/month | 1,000 requests/hour | All prediction endpoints, batch (1000 pairs), monthly dataset export (100k rows), model version selection |
| **Enterprise** | $299/month | 10,000 requests/hour | Everything + unlimited batch, daily dataset exports, webhook notifications, priority support, custom model training |
| **Dataset License** | $999/one-time | N/A | Full prediction_connections snapshot (current model), delivered as Parquet. Updates available quarterly for $299. |

### 6.2 Revenue Model Options

**Option A: SaaS API (Recommended Start)**
- Stripe integration (already partially built in `daily_handlers.go` with `stripe-go`)
- Usage-based billing with monthly plans
- Free tier as acquisition funnel
- Upgrade triggers: rate limit hits, batch needs, export requests

**Option B: Licensed Dataset**
- Quarterly snapshots of all predictions
- Delivered as Parquet/CSV with documentation
- Includes model metadata and feature definitions
- Better for enterprise customers who want to run their own analyses

**Option C: Hybrid (Recommended Long-term)**
- API access for real-time queries
- Licensed datasets for bulk analysis
- Custom model training for enterprise (train on their private artist data)
- Consulting for integration support

### 6.3 Billing Implementation

```
Stripe Flow:
1. User signs up -> creates api_users row with tier='free'
2. User upgrades -> Stripe checkout session (existing code pattern in daily_handlers.go)
3. Webhook confirms payment -> update tier in api_users
4. Middleware checks tier on every request -> enforces rate limits
5. Monthly usage report -> Stripe invoice for overage (enterprise)
```

### 6.4 Go-to-Market Sequence

| Phase | Timeline | Actions |
|-------|----------|---------|
| **Phase 1: API Launch** | Weeks 1-4 | Clean up existing endpoints, add auth middleware, deploy behind TLS, publish OpenAPI docs |
| **Phase 2: Free Tier** | Weeks 5-8 | Launch free tier with rate limits, blog post/Product Hunt, collect feedback |
| **Phase 3: Paid Tiers** | Weeks 9-12 | Implement Stripe billing, add batch/export endpoints, launch researcher tier |
| **Phase 4: Enterprise** | Months 4-6 | Custom model training, SLA guarantees, dataset licensing, enterprise sales |

---

## 7. Architecture Summary

```
┌──────────────────────────────────────────────────────────────────┐
│                     EXTERNAL USERS                                │
│         Primary (API)              Secondary (Web UI)             │
│    curl / SDK / notebooks        browser at :8080/ml              │
└───────┬───────────────────────────────┬──────────────────────────┘
        │                               │
        │  REST API                     │  HTML + JS
        ▼                               ▼
┌───────────────┐              ┌─────────────────┐
│  API Gateway  │              │  Go Frontend    │
│  (nginx/Caddy)│              │  (:8080)        │
│  TLS, Rate    │              │  Templates,     │
│  Limiting     │──────────────│  Auth, Proxy    │
└───────┬───────┘              └────────┬────────┘
        │                               │
        │  Internal Docker Network      │  HTTP to ml:8000
        ▼                               ▼
┌──────────────────────────────────────────────────────┐
│                 ML Service (FastAPI :8000)            │
│                                                      │
│  /predict/connection    /predict/neighbors            │
│  /generate/tracks       /synthetic-tracks-similarity  │
│  /explore/what-if       /trends/daily                 │
│  /dataset/export        /model/feedback               │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ Link     │  │ CVAE     │  │ Track            │   │
│  │ Predictor│  │ Generator│  │ Similarity       │   │
│  │ (Logit)  │  │ (PyTorch)│  │ (Aitchison)      │   │
│  └──────────┘  └──────────┘  └──────────────────┘   │
└───────────────────────┬──────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────┐
│              PostgreSQL (musicbrainz_db)              │
│                                                      │
│  artist, artist_collab, artist_embeddings_n2v,       │
│  prediction_connections, synthetic_tracks,            │
│  synthetic_tracks_high_level_features,               │
│  api_users, api_usage_log, daily_predictions,        │
│  prediction_feedback, scenario_cache                 │
└──────────────────────────────────────────────────────┘
```

---

## 8. Immediate Next Steps

1. **Security**: Remove hardcoded credentials from config.py, rotate keys
2. **API auth middleware**: Implement api_key validation + rate limiting in FastAPI
3. **Artist profile endpoint**: Build `/api/v1/artist/{id}/profile` as the foundation
4. **What-if endpoint**: Build the "what would happen if X and Y collaborated?" flow
5. **Batch endpoint**: Enable bulk predictions for API customers
6. **Export endpoint**: CSV/Parquet download of filtered predictions
7. **Stripe integration**: Wire up billing using existing stripe-go patterns
8. **Monitoring**: Add latency/error tracking, model performance dashboards
