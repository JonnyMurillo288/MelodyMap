# Synthetic Tracks Database

This document describes the synthetic tracks database architecture, how synthetic tracks are generated, and how the system works end-to-end.

## Overview

The Synthetic Tracks Database stores AI-generated track features for hypothetical collaborations between artists who haven't worked together yet. The system uses machine learning models to:

1. **Predict artist collaboration probability** - Using a logistic regression model to determine how likely two artists are to collaborate
2. **Generate synthetic track features** - Using a Conditional Variational Autoencoder (CVAE) to generate realistic audio features for hypothetical collaboration tracks

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Frontend (Go)                                   │
│   - Requests neighbor predictions for an artist                             │
│   - Retrieves synthetic track features from database                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ML Service (Python/FastAPI)                        │
│   ┌─────────────────────┐    ┌──────────────────────────┐                   │
│   │  Link Predictor     │    │  Track Feature Generator │                   │
│   │  (Logistic Reg)     │───▶│  (CVAE Model)            │                   │
│   │                     │    │                          │                   │
│   │  Predicts P(link)   │    │  Generates track features│                   │
│   │  between artists    │    │  conditioned on artists  │                   │
│   └─────────────────────┘    └──────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PostgreSQL Database                                 │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  synthetic_tracks                                                    │   │
│   │  - track_id (PK, auto-generated)                                    │   │
│   │  - src_artist_id (UUID)                                             │   │
│   │  - dst_artist_id (UUID)                                             │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  synthetic_tracks_high_level_features                               │   │
│   │  - track_id (FK → synthetic_tracks)                                 │   │
│   │  - danceability, genre_*, mood_*, timbre_*, etc.                   │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  synthetic_track_model_versions                                     │   │
│   │  - track_id (FK → synthetic_tracks)                                 │   │
│   │  - model_name, version, created_at                                  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Database Schema

### `synthetic_tracks`

The main table storing synthetic track metadata and artist pair relationships.

| Column | Type | Description |
|--------|------|-------------|
| `track_id` | INT (PK, auto) | Unique identifier for the synthetic track |
| `src_artist_id` | UUID | Source artist MusicBrainz ID |
| `dst_artist_id` | UUID | Destination artist MusicBrainz ID |

**Constraints:**
- Primary key on `track_id`
- Unique constraint on `(src_artist_id, dst_artist_id)` pair

### `synthetic_tracks_high_level_features`

Stores the predicted audio features for each synthetic track. Schema mirrors `high_level_track_audio_features` but references synthetic tracks.

| Column | Type | Description |
|--------|------|-------------|
| `track_id` | INT (PK, FK) | References `synthetic_tracks.track_id` |
| `danceability` | FLOAT | Predicted danceability score |
| `gender_female` | FLOAT | Predicted female vocal probability |
| `gender_male` | FLOAT | Predicted male vocal probability |
| `genre_dortmund_*` | FLOAT | Genre classification scores (9 genres) |
| `genre_electronic_*` | FLOAT | Electronic subgenre scores (5 subgenres) |
| `genre_rosamerica_*` | FLOAT | Rosamerica genre scores (8 genres) |
| `genre_tzanetakis_*` | FLOAT | Tzanetakis genre scores (10 genres) |
| `ismir04_rhythm_*` | FLOAT | Rhythm classification scores |
| `mood_*` | FLOAT | Mood prediction scores (7 moods) |
| `moods_mirex_cluster*` | FLOAT | MIREX mood cluster scores (5 clusters) |
| `timbre_bright` | FLOAT | Timbre brightness score |
| `timbre_dark` | FLOAT | Timbre darkness score |
| `tonal_atonal_*` | FLOAT | Tonal/atonal classification |
| `voice_instrumental_*` | FLOAT | Voice vs instrumental classification |

### `synthetic_track_model_versions`

Tracks which ML model version generated each synthetic track.

| Column | Type | Description |
|--------|------|-------------|
| `track_id` | INT (PK, FK) | References `synthetic_tracks.track_id` |
| `model_name` | TEXT | Name of the model (e.g., "cvae") |
| `version` | TEXT | Model version (e.g., "v1") |
| `created_at` | TIMESTAMPTZ | When the track was generated |

## ML Models

### 1. Link Predictor (Logistic Regression)

**Purpose:** Predicts the probability that two artists would collaborate.

**Input Features:**
- `cos_sim_src_dst` - Cosine similarity between artist embeddings
- `l2_dist_src_dst` - L2 distance between artist embeddings
- `dot_src_dst` - Dot product of embeddings
- `popularity_src`, `popularity_dst` - Artist popularity scores
- `max_cos_srcnbr_dst`, `mean_cos_srcnbr_dst` - Neighbor proximity metrics
- `shared_neighbors`, `jaccard_neighbors` - Graph structure features
- `adamic_adar`, `preferential_attachment` - Link prediction features

**Output:** Probability score [0, 1] indicating collaboration likelihood

**Location:** `internal/interlude_service/machinelearning/models/link_predictor.py`

### 2. Track Feature Generator (CVAE)

**Purpose:** Generates realistic audio features for hypothetical collaboration tracks.

**Conditioning Features (C_COLS):**
```python
[
    "cos_sim_src_dst",      # How similar are the artists?
    "l2_dist_src_dst",      # Distance in embedding space
    "popularity_src",       # Source artist popularity
    "popularity_dst",       # Destination artist popularity
    "mean_topk_cos_dstnbr_src",  # Neighbor proximity
    "mean_topk_cos_srcnbr_dst",
    "shared_neighbors",     # Common collaborators
]
```

**Generated Features (Y_CONT_COLS):**
- Danceability
- Gender classification (female/male)
- Genre classifications (Dortmund, Electronic, Rosamerica, Tzanetakis)
- Rhythm classifications (ISMIR04)
- Mood scores (acoustic, aggressive, electronic, happy, party, relaxed, sad)
- MIREX mood clusters
- Timbre (bright/dark)
- Tonal classification
- Voice/instrumental classification

**Model Architecture:**
```
Encoder: q(z | y_cont, c) → μ, logvar
Decoder: p(y_cont, y_bin | z, c)

- z_dim: 16 (latent space dimension)
- hidden: (256, 256) (MLP hidden layers)
- dropout: 0.1
```

**Location:** `internal/interlude_service/machinelearning/models/track_feature_predictor.py`

## API Endpoints

### POST `/ml/predict/artist-link`

Predicts collaboration probability and generates synthetic tracks for a specific artist pair.

**Request:**
```json
{
    "src_artist_id": "uuid-string",
    "dst_artist_id": "uuid-string",
    "limit": 25,
    "model_version": "logit_v1"
}
```

**Response:**
```json
{
    "name": "Artist Name",
    "neighbors": [
        {
            "name": "Neighbor Artist",
            "tracks": [1, 2, 3],  // synthetic track IDs
            "probability": 0.85
        }
    ],
    "model_version": "logit_v1",
    "latency_ms": 150.5
}
```

### POST `/ml/predict/artist-neighbors`

Predicts top-k most likely collaborators for a source artist.

**Request:**
```json
{
    "src_artist_id": "uuid-string",
    "limit": 25,
    "model_version": "logit_v1"
}
```

### POST `/ml/generate/tracks`

Generates synthetic track features for a specific artist pair.

**Request:**
```json
{
    "src_artist_id": "uuid-string",
    "dst_artist_id": "uuid-string",
    "limit": 5,
    "model_version": "cvae_v1"
}
```

## Data Flow

### Generation Pipeline

1. **User requests artist neighbors**
   - Frontend sends artist MBID to ML service

2. **Link prediction**
   - Build artist pair embeddings from graph features
   - Run logistic regression model to get collaboration probabilities
   - Filter by threshold (default: 0.5)

3. **Synthetic track generation**
   - For each predicted link, extract conditioning features
   - Run CVAE decoder to sample track features from latent space
   - Average multiple samples (n=50) for stable predictions

4. **Database insertion**
   - Insert new row into `synthetic_tracks` with artist pair
   - Insert generated features into `synthetic_tracks_high_level_features`
   - Record model version in `synthetic_track_model_versions`

5. **Return to frontend**
   - Return inserted track IDs
   - Frontend can query track features by ID

### Retrieval Pipeline

```go
// Go backend retrieves synthetic track features
func GetSyntheticTrackFeaturesByGIDs(
    ctx context.Context,
    store *Store,
    trackIDs []int,
    limit int,
) (map[string]SyntheticRecordingFeatures, error)
```

## Go Types

### `SyntheticRecordingFeatures`

```go
type SyntheticRecordingFeatures struct {
    SrcArtistID string    `json:"src_artist_id"`
    DstArtistID string    `json:"dst_artist_id,omitempty"`
    TrackID     string    `json:"track_id"`

    Danceability NullFloat `json:"danceability"`
    GenderFemale NullFloat `json:"gender_female"`
    GenderMale   NullFloat `json:"gender_male"`

    // Genre classifications (Dortmund, Electronic, Rosamerica, Tzanetakis)
    GenreDortmundAlternative NullFloat `json:"genre_dortmund_alternative"`
    // ... (all genre fields)

    // Rhythm, Mood, Timbre, Tonal, Voice fields
    // ... (all audio feature fields)
}
```

### `SyntheticFrontendTracksList`

```go
type SyntheticFrontendTracksList struct {
    FeaturesMap map[string]SyntheticRecordingFeatures `json:"featuresMap"`
}
```

## Database Initialization

The synthetic track tables are created automatically on service startup:

```go
func InitSyntheticTrackTables(ctx context.Context, store *Store) error
```

This function:
1. Creates `synthetic_tracks` table if not exists
2. Creates `synthetic_tracks_high_level_features` based on real features table schema
3. Creates `synthetic_track_model_versions` for version tracking
4. Sets up foreign key constraints and cascading deletes

## Constraints and Limits

- Maximum 100 synthetic tracks per artist pair (enforced in insert query)
- Neighbor prediction limit: 1-100 artists
- Track generation limit: 1-25 tracks per request
- Unique constraint prevents duplicate artist pairs

## Model Artifacts

Model files are stored in `internal/interlude_service/machinelearning/model_engineering/`:

- `logit_model_v1.joblib` - Link prediction model
- `cvae_artifacts/` - CVAE model directory
  - `model.pt` - PyTorch model weights
  - `prep.pkl` - Preprocessor (scalers, imputers)
  - `meta.json` - Model metadata and column definitions
