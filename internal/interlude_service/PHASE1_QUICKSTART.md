# Phase 1 Quickstart

Get the Interlude API running locally and test every endpoint.

---

## Prerequisites

- Docker + Docker Compose
- PostgreSQL running locally with `musicbrainz_db`
- `.env.docker` in the repo root (already set up)

---

## Step 1: Run the Migration

This creates the new tables and seeds your test account.

```bash
psql -U postgres -d musicbrainz_db -f internal/interlude_service/machinelearning/migrations/001_phase1_tables.sql
```

---

## Step 2: Start the Stack

```bash
docker compose up --build
```

Services:
| Service | Port | URL |
|---------|------|-----|
| Go frontend | 8080 | http://localhost:8080 |
| ML API (direct) | 8002 | http://localhost:8002 |
| Caddy (TLS proxy) | 443 / 80 | https://localhost |

---

## Step 3: Verify

```bash
# Health check (no auth needed)
curl http://localhost:8002/api/v1/health

# List available models (no auth needed)
curl http://localhost:8002/api/v1/models
```

---

## Your Test Account

The migration seeds an admin account with full enterprise access and no rate limit.

| Field | Value |
|-------|-------|
| **API Key** | `interlude-test-key-do-not-share-2026` |
| **Email** | admin@interlude.local |
| **Tier** | enterprise |
| **Rate Limit** | 999,999 / hour (effectively unlimited) |

Use this key in all requests below via the `X-API-Key` header.

```bash
export API_KEY="interlude-test-key-do-not-share-2026"
```

---

## Test Every Endpoint

### 1. Predict Connection (single pair)

Predict the collaboration probability between two artists. Replace MBIDs with real ones from your database.

```bash
# Find some artist MBIDs to use
psql -U postgres -d musicbrainz_db -c "
  SELECT a.gid, a.name FROM artist a
  JOIN artist_embeddings_n2v e ON a.id = e.artist_id
  LIMIT 5;
"

# Predict
curl -s -X POST http://localhost:8002/api/v1/predict/connection \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "src_artist": "89ad4ac3-39f7-470e-963a-56509c546377",
    "dst_artist": "10adbe5e-a2c0-4bf3-8249-2b4cbf6e6ca8"
  }' | python3 -m json.tool
```

**Expected response shape**:
```json
{
  "data": {
    "src_artist": "...",
    "dst_artist": "...",
    "src_name": "Artist A",
    "dst_name": "Artist B",
    "probability": 0.73,
    "tracks": [101, 102, 103],
    "features_used": { "cos_sim_src_dst": 0.85, ... }
  },
  "meta": {
    "model_version": "v5",
    "latency_ms": 1234.5,
    "cached": false,
    "request_id": "uuid"
  }
}
```

### 2. Predict Neighbors (top-k discovery)

```bash
curl -s -X POST http://localhost:8002/api/v1/predict/neighbors \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "artist": "89ad4ac3-39f7-470e-963a-56509c546377",
    "limit": 10
  }' | python3 -m json.tool
```

### 3. Batch Prediction (multiple pairs at once)

```bash
curl -s -X POST http://localhost:8002/api/v1/predict/batch \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "pairs": [
      {"src": "MBID_1", "dst": "MBID_2"},
      {"src": "MBID_3", "dst": "MBID_4"}
    ]
  }' | python3 -m json.tool
```

### 4. A/B Compare Models (Strategy 4.2)

Compare how different model versions score the same pair. This is your tool for deciding which model to make the default.

```bash
curl -s -X POST http://localhost:8002/api/v1/predict/compare \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "src_artist": "89ad4ac3-39f7-470e-963a-56509c546377",
    "dst_artist": "10adbe5e-a2c0-4bf3-8249-2b4cbf6e6ca8",
    "versions": ["v1", "v3", "v5"]
  }' | python3 -m json.tool
```

**Expected output**: Side-by-side probabilities from each version.

### 5. Generate Synthetic Tracks

```bash
curl -s -X POST http://localhost:8002/api/v1/generate/tracks \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "src_artist": "89ad4ac3-39f7-470e-963a-56509c546377",
    "dst_artist": "31810c40-932a-4f2d-8cfd-17849844e2a6",
    "num_tracks": 5
  }' | python3 -m json.tool
```

### 6. Find Similar Real Tracks (Playlist Generation)

Use the `track_id` values from step 5:

```bash
curl -s -X POST http://localhost:8002/api/v1/generate/playlist \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "synthetic_track_ids": [TRACK_ID_1, TRACK_ID_2],
    "num_similar": 5
  }' | python3 -m json.tool
```

### 7. Artist Profile

```bash
curl -s http://localhost:8002/api/v1/artist/PASTE_MBID/profile \
  -H "X-API-Key: $API_KEY" | python3 -m json.tool
```

**Returns**: name, MBID, Spotify ID, popularity, genre distribution, top collaborators, embedding availability.

### 8. Submit Feedback (Strategy 4.2)

```bash
curl -s -X POST http://localhost:8002/api/v1/feedback \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "prediction_src": "PASTE_MBID_1",
    "prediction_dst": "PASTE_MBID_2",
    "rating": 4,
    "comment": "This connection makes sense musically"
  }' | python3 -m json.tool
```

---

## Test Model Switching

The whole point of the plug-and-play system. Same endpoint, different model:

```bash
# Default (v5)
curl -s -X POST http://localhost:8002/api/v1/predict/connection \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"src_artist": "MBID_1", "dst_artist": "MBID_2"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'v5: {d[\"data\"][\"probability\"]}')"

# Force v3
curl -s -X POST http://localhost:8002/api/v1/predict/connection \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"src_artist": "MBID_1", "dst_artist": "MBID_2", "model_version": "v3"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'v3: {d[\"data\"][\"probability\"]}')"

# Force v1
curl -s -X POST http://localhost:8002/api/v1/predict/connection \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"src_artist": "MBID_1", "dst_artist": "MBID_2", "model_version": "v1"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'v1: {d[\"data\"][\"probability\"]}')"
```

---

## Check Metrics (Strategy 4.3)

After running some requests:

```bash
# Raw Prometheus metrics
curl -s http://localhost:8002/metrics | grep interlude_

# Prediction distribution
curl -s http://localhost:8002/metrics | grep interlude_prediction_probability

# Latency percentiles
curl -s http://localhost:8002/metrics | grep interlude_request_latency

# Cache hit rate
curl -s http://localhost:8002/metrics | grep interlude_cache_hits

# API calls by tier
curl -s http://localhost:8002/metrics | grep interlude_api_calls
```

---

## Check Rate Limiting

Your test account has 999,999/hr so you won't hit it normally. To test rate limiting works, register a free account:

```bash
# Register free account
FREE_KEY=$(curl -s -X POST http://localhost:8002/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "free@test.com"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['api_key'])")

echo "Free key: $FREE_KEY"

# Check rate limit headers
curl -s -I -X POST http://localhost:8002/api/v1/predict/connection \
  -H "X-API-Key: $FREE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"src_artist": "MBID_1", "dst_artist": "MBID_2"}' \
  | grep -i ratelimit
```

---

## Browse the Docs

Interactive Swagger UI with all endpoints, schemas, and try-it-out:

```
http://localhost:8002/docs
```

Alternative (ReDoc, cleaner for reading):

```
http://localhost:8002/redoc
```

---

## Verify Legacy Endpoints Still Work

The old endpoints should be completely unaffected:

```bash
# Old neighbor prediction (uses SDS token, not API key)
curl -s -X POST http://localhost:8002/ml/predict/artist-neighbors \
  -H "Content-Type: application/json" \
  -d '{"src_artist_id": "PASTE_MBID", "limit": 10}'

# Old link prediction
curl -s -X POST http://localhost:8002/ml/predict/artist-link \
  -H "Content-Type: application/json" \
  -d '{"src_artist_id": "PASTE_MBID_1", "dst_artist_id": "PASTE_MBID_2"}'
```

---

## Troubleshooting

**"Missing X-API-Key header"**: You're hitting a `/api/v1/*` endpoint without the key. Add `-H "X-API-Key: $API_KEY"`.

**"Invalid API key"**: Make sure the migration ran. Check: `psql -U postgres -d musicbrainz_db -c "SELECT email, tier FROM api_users;"`

**"Model version 'vX' not found"**: The model file doesn't exist on disk. Check: `ls internal/interlude_service/machinelearning/feature_engineering/logit_model_*.joblib`

**ML service not starting**: Check Docker logs: `docker compose logs ml`

**"Artist not found"**: The MBID doesn't exist in your database or the artist has no embeddings. Use the SQL query from Step 1 to find valid MBIDs.
