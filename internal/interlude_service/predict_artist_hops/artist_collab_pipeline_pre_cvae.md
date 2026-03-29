# Artist Collaboration & Track Feature Prediction Pipeline  
*(Up to CVAE Input Construction)*

## Overview

This document describes the end-to-end data and modeling pipeline used to predict likely artist collaborations and construct structured feature inputs for downstream generative models (e.g., CVAE). The system combines **graph structure**, **artist embeddings**, **track-level audio features**, and **collaboration history** to produce a supervised learning dataset suitable for conditional generation.

The pipeline answers two core questions:

1. **Will two artists collaborate?** (link prediction)  
2. **If they do, what would the resulting track look like?** (feature construction for generation)

This document covers everything **up to** the CVAE.

---

## Data Sources

### 1. Artist Collaboration Graph
- Nodes: artists  
- Edges: existing collaborations  
- Edge metadata:
  - `recording_id`
  - collaboration count
  - timestamps (if available)

### 2. Artist Embeddings
- Learned via Node2Vec (or equivalent)
- Captures:
  - graph proximity
  - stylistic similarity
- Stored per artist:
  ```
  artist_id
  emb_0 ... emb_n
  ```

### 3. Track-Level Audio Features
From **AcousticBrainz** (high-level features):

- Genre probabilities
- Mood / emotion
- Rhythm
- Timbre-related features

These are stored at the **recording** level and later aggregated.

---

## Step 1 — Audio Feature Construction (Recording → Artist Pair)

### Goal
Map track-level audio features to artist pairs in the collaboration graph.

### Logic
If a collaboration exists between `src` and `dst`:

1. Identify the shared `recording_id`
2. Join with AcousticBrainz features
3. Associate audio features with `(src, dst)`

### Resulting Table
**`artist_pair_audio_features`**
```
src_artist_id
dst_artist_id
recording_id
audio_feature_1
audio_feature_2
...
```

If multiple recordings exist:
- Aggregate (mean / max / weighted mean)
- Preserve distribution statistics where useful

---

## Step 2 — Artist Pair Feature Engineering

For every `(src, dst)` pair (both positive and negative examples), compute:

### A. Embedding-Based Features
- Cosine similarity: `cos(src_emb, dst_emb)`
- Euclidean distance
- PCA / reduced-space distances (optional)

### B. Neighborhood Reachability Features
Approximate 1–2 hop connectivity without BFS:

- Max similarity between `src` neighbors and `dst`
- Mean top-k similarity
- Shared neighbor count
- Jaccard overlap

### C. Popularity & Context
- Artist popularity (Spotify, Last.fm)
- Popularity delta: `pop(src) - pop(dst)`
- Historical collaboration counts

---

## Step 3 — Link Prediction Model

### Objective
Estimate probability that two artists will collaborate.

### Target
```
y = 1 if collaboration exists
y = 0 otherwise
```

### Model
- Logistic Regression / Elastic Net (baseline)
- Inputs:
  - embedding features
  - neighborhood features
  - popularity features

### Outputs
For each `(src, dst)` pair:
```
P(collaboration | features)
```

This probability is later used to:
- Rank candidate collaborations
- Weight downstream generative inputs

---

## Step 4 — Track Feature Prediction Target (`Y`)

### Goal
Define what the CVAE will generate.

### Target Variable (`Y`)
Predicted **track-level audio feature vector** for a hypothetical collaboration.

Constructed from:
- Existing collaborations (ground truth)
- Aggregated AcousticBrainz features

```
Y = [
  genre_probs,
  mood_probs,
  rhythm_features,
  timbre_features,
  ...
]
```

---

## Step 5 — CVAE Conditioning Inputs (`X`)

### Conditioning Vector Structure

For each `(src, dst)` pair:

#### Artist Information
- `src_embedding`
- `dst_embedding`

#### Relationship Features
- embedding similarity metrics
- neighborhood reachability features
- collaboration probability (from link model)

#### Popularity Context
- `pop(src)`
- `pop(dst)`
- expected popularity of track

```
X = concat(
  src_emb,
  dst_emb,
  pair_features,
  popularity_features
)
```

---

## Final Dataset Schema (Pre-CVAE)

### Input
```
X ∈ R^d
```

### Output
```
Y ∈ R^k
```

Each row represents:

> *If artist A and artist B collaborated, conditioned on their relationship and context, what would the track sound like?*

---

## What the CVAE Will Learn (Next Stage)

- Latent structure of successful collaborations
- Multimodal distributions over audio features
- Conditional generation under constraints:
  - genre bias
  - popularity optimization
  - stylistic blending

---

## Notes & Design Rationale

- Graph embeddings encode **creative proximity**
- Audio features encode **sonic outcome**
- Link prediction acts as a **feasibility prior**
- CVAE enables **diverse but plausible generation**

This separation keeps:
- prediction interpretable
- generation flexible
- business use cases modular (ranking, synthesis, licensing)
