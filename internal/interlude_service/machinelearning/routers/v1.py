"""
/api/v1/ router — public API endpoints for the Interlude service.

All existing model files and inference logic remain untouched.
This router wraps the same functions that the legacy /ml/* endpoints use,
but with standardized schemas, model registry integration, and metrics.
"""
import os
import time
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Request

from models.model_registry import registry, LOGIT_VERSION_TO_ID
from schemas.v1 import (
    APIResponse, ResponseMeta, ErrorResponse, APIError,
    ConnectionRequest, ConnectionData,
    NeighborRequest, NeighborsData, NeighborItem,
    BatchRequest, BatchData, BatchResultItem,
    CompareRequest, CompareData, CompareResultItem,
    TrackGenRequest, TrackGenData, SyntheticTrackItem,
    PlaylistRequest, PlaylistData, SimilarTrackItem,
    ArtistProfileData,
    RegisterRequest, RegisterResponse,
    ModelInfoData,
    HealthData,
    FeedbackRequest,
    # Phase 2
    WhatIfRequest, WhatIfData, WhatIfPairResult,
    FeaturedConnection, DailyTrendsData,
    DatasetExportParams,
    UpgradeTierRequest,
)
from middleware.metrics import (
    observe_prediction,
    observe_cache,
    PLAYLIST_CREATIONS,
    FEEDBACK_SUBMISSIONS,
    DATASET_EXPORTS,
)
from config.config import LINK_PREDICTION_FEATURES
from config.cvae_config import C_COLS, Y_CONT_COLS, Y_BIN_COLS
from utils.database import get_pg_conn

# Snapshot the original 11 features BEFORE pipeline_links mutates the global list
# by appending genre similarity columns. The model was trained on these 11.
_LOGIT_FEATURES = list(LINK_PREDICTION_FEATURES)

v1 = APIRouter(prefix="/api/v1", tags=["v1"])


# ---------------------------------------------------------------
# Helpers (reuse existing app.py functions without modifying them)
# ---------------------------------------------------------------
def _get_id_from_mbid(artist_id: str) -> int:
    conn = get_pg_conn()
    q = "SELECT id FROM artist WHERE gid = %s::uuid;"
    df = pd.read_sql_query(q, conn, params=(artist_id,))
    conn.close()
    if df.empty:
        raise HTTPException(status_code=404, detail=f"Artist not found: {artist_id}")
    return int(df["id"].iloc[0])


def _get_mbid_from_id(artist_id: int) -> str:
    conn = get_pg_conn()
    q = "SELECT gid FROM artist WHERE id = %s::int;"
    df = pd.read_sql_query(q, conn, params=(artist_id,))
    conn.close()
    if df.empty:
        raise HTTPException(status_code=404, detail=f"Artist ID not found: {artist_id}")
    return str(df["gid"].iloc[0])


def _get_name_from_id(artist_id: int) -> str:
    conn = get_pg_conn()
    q = "SELECT name FROM artist WHERE id = %s::int;"
    df = pd.read_sql_query(q, conn, params=(artist_id,))
    conn.close()
    if df.empty:
        return "Unknown"
    return str(df["name"].iloc[0])


def _get_name_from_mbid(mbid: str) -> str:
    conn = get_pg_conn()
    q = "SELECT name FROM artist WHERE gid = %s::uuid;"
    df = pd.read_sql_query(q, conn, params=(mbid,))
    conn.close()
    if df.empty:
        return "Unknown"
    return str(df["name"].iloc[0])


def _resolve_artist(raw: str) -> int:
    """Resolve an artist string (MBID, int ID, or name) to an integer artist ID."""
    # Try as UUID (MBID)
    if len(raw) == 36 and raw.count("-") == 4:
        return _get_id_from_mbid(raw)

    # Try as integer ID
    try:
        return int(raw)
    except ValueError:
        pass

    # Try as name
    try:
        conn = get_pg_conn()
        q = "SELECT id FROM artist WHERE LOWER(name) = LOWER(%s) LIMIT 1;"
        df = pd.read_sql_query(q, conn, params=(raw,))
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error resolving artist '{raw}': {e}")
    if df.empty:
        raise HTTPException(status_code=404, detail=f"Artist not found: '{raw}'. Try a different spelling or use a MusicBrainz ID.")
    return int(df["id"].iloc[0])


def _build_meta(version: str, latency: float, cached: bool, request: Request) -> ResponseMeta:
    return ResponseMeta(
        model_version=version,
        latency_ms=round(latency, 2),
        cached=cached,
        request_id=getattr(request.state, "request_id", ""),
    )


# ---------------------------------------------------------------
# GET /api/v1/models
# ---------------------------------------------------------------
@v1.get("/models", response_model=APIResponse)
async def list_models(request: Request):
    """List available model versions and defaults."""
    info = registry.list_available()
    return APIResponse(
        data=ModelInfoData(**info),
        meta=_build_meta("", 0, False, request),
    )


# ---------------------------------------------------------------
# GET /api/v1/health
# ---------------------------------------------------------------
@v1.get("/health", response_model=APIResponse)
async def health_check(request: Request):
    """Health check with model and DB status."""
    db_ok = False
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        conn.close()
        db_ok = True
    except Exception:
        pass

    info = registry.list_available()
    return APIResponse(
        data=HealthData(
            status="healthy" if db_ok else "degraded",
            models_loaded=info.get("currently_loaded", []),
            db_connected=db_ok,
        ),
        meta=_build_meta("", 0, False, request),
    )


# ---------------------------------------------------------------
# POST /api/v1/auth/register
# ---------------------------------------------------------------
@v1.post("/auth/register", response_model=RegisterResponse)
async def register(req: RegisterRequest):
    """Register for a free-tier API key."""
    from middleware.auth import register_api_user
    result = register_api_user(email=req.email, org_name=req.org_name)
    return RegisterResponse(**result)


# ---------------------------------------------------------------
# POST /api/v1/predict/connection
# ---------------------------------------------------------------
@v1.post("/predict/connection", response_model=APIResponse)
async def predict_connection(req: ConnectionRequest, request: Request):
    """Predict collaboration probability between two specific artists.

    Uses the model registry for plug-and-play version selection.
    Pass model_version='v3' to use v3 instead of the default v5, etc.
    """
    start = time.time()

    src_int = _resolve_artist(req.src_artist)
    dst_int = _resolve_artist(req.dst_artist)
    src_name = _get_name_from_id(src_int)
    dst_name = _get_name_from_id(dst_int)

    # Load model from registry (plug-and-play)
    model, version = registry.get_logit(req.model_version)
    model_id = LOGIT_VERSION_TO_ID.get(version, 5)

    # Check cache first (version-aware)
    from app import check_prediction_connections, check_existing_synthetic_tracks
    cached = check_prediction_connections(str(src_int), str(dst_int), model_id=model_id)
    if cached:
        observe_cache("prediction", True)
        # Fetch cached probability
        conn = get_pg_conn()
        q = """SELECT prob FROM prediction_connections
               WHERE src::int = %s AND dst::int = %s AND model_id = %s LIMIT 1"""
        df = pd.read_sql_query(q, conn, params=(src_int, dst_int, model_id))
        conn.close()
        prob = float(df["prob"].iloc[0]) if not df.empty else 0.0

        # Get existing synthetic tracks (version-aware)
        existing = check_existing_synthetic_tracks(str(src_int), str(dst_int), limit=req.limit, cvae_version=version)
        track_ids = [tid for tid, _ in existing]

        observe_prediction(prob, version)
        return APIResponse(
            data=ConnectionData(
                src_artist=req.src_artist,
                dst_artist=req.dst_artist,
                src_name=src_name,
                dst_name=dst_name,
                probability=prob,
                tracks=track_ids,
            ),
            meta=_build_meta(version, (time.time() - start) * 1000, True, request),
        )

    observe_cache("prediction", False)

    # Run inference using existing pipeline
    from features.pipeline_links import build_link_prediction_embeddings_from_artist_list
    artist_embeddings = build_link_prediction_embeddings_from_artist_list([(src_int, dst_int)])
    X = artist_embeddings[_LOGIT_FEATURES].values
    probs = model.predict_proba(X)
    if probs.ndim > 1 and probs.shape[1] > 1:
        probs = probs[:, 1]
    probs = np.clip(probs, 0.0, 0.99)
    prob = float(probs[0])

    # Save prediction (version-aware)
    from app import save_predictions_to_db, generate_synthetic_tracks
    pred_df = pd.DataFrame({"src": [src_int], "dst": [dst_int], "prob": [prob]})
    save_predictions_to_db(pred_df, model_id=model_id)

    # Generate synthetic tracks
    artist_embeddings["prob"] = prob
    track_ids = generate_synthetic_tracks(
        cvae_version=version,
        df_pred_links=artist_embeddings,
        limit=req.limit,
    )

    observe_prediction(prob, version)

    return APIResponse(
        data=ConnectionData(
            src_artist=req.src_artist,
            dst_artist=req.dst_artist,
            src_name=src_name,
            dst_name=dst_name,
            probability=prob,
            tracks=track_ids,
            features_used=dict(zip(_LOGIT_FEATURES, X[0].tolist())),
        ),
        meta=_build_meta(version, (time.time() - start) * 1000, False, request),
    )


# ---------------------------------------------------------------
# POST /api/v1/predict/neighbors
# ---------------------------------------------------------------
@v1.post("/predict/neighbors", response_model=APIResponse)
async def predict_neighbors(req: NeighborRequest, request: Request):
    """Get top-k predicted neighbors for one artist.

    Uses cached predictions when available (fast path).
    Falls back to full ML pipeline on cache miss (slow path).
    """
    start = time.time()

    src_int = _resolve_artist(req.artist)
    src_name = _get_name_from_id(src_int)
    model, version = registry.get_logit(req.model_version)
    model_id = LOGIT_VERSION_TO_ID.get(version, 5)

    # Check cache (version-aware)
    from app import get_prediction_connections_for_src, check_existing_synthetic_tracks
    pred_connections = get_prediction_connections_for_src(src_int, limit=req.limit, model_id=model_id)

    neighbors = []

    if len(pred_connections) >= req.limit:
        observe_cache("prediction", True)
        for _, row in pred_connections.iterrows():
            dst_int = int(row["dst"])
            prob = float(row["prob"])

            if req.min_probability and prob < req.min_probability:
                continue

            dst_mbid = _get_mbid_from_id(dst_int)
            dst_name = _get_name_from_id(dst_int)

            existing = check_existing_synthetic_tracks(src=src_int, dst=dst_int, limit=5)
            track_ids = [tid for tid, _ in existing]

            observe_prediction(prob, version)
            neighbors.append(NeighborItem(
                artist_id=dst_mbid,
                name=dst_name,
                probability=prob,
                tracks=track_ids,
            ))
    else:
        observe_cache("prediction", False)
        # Slow path: full ML pipeline
        from models.link_predictor import predict_link_features_from_artist
        preds = predict_link_features_from_artist(
            model=model,
            features=_LOGIT_FEATURES,
            THRESHOLD=0.3,
            input_artist_id=src_int,
            num_candidates=582964 // 20,
            random_state=67,
        )
        preds = preds.loc[preds.src == src_int]

        from app import save_predictions_to_db
        save_predictions_to_db(preds, model_id=model_id)

        for i in range(min(req.limit, len(preds))):
            dst_int = int(preds.dst.iloc[i])
            prob = float(preds.prob.iloc[i])

            if req.min_probability and prob < req.min_probability:
                continue

            dst_mbid = _get_mbid_from_id(dst_int)
            dst_name = _get_name_from_id(dst_int)

            observe_prediction(prob, version)
            neighbors.append(NeighborItem(
                artist_id=dst_mbid,
                name=dst_name,
                probability=prob,
                tracks=[],
            ))

    return APIResponse(
        data=NeighborsData(
            artist=req.artist,
            artist_name=src_name,
            neighbors=neighbors,
        ),
        meta=_build_meta(version, (time.time() - start) * 1000, len(pred_connections) >= req.limit, request),
    )


# ---------------------------------------------------------------
# POST /api/v1/predict/batch
# ---------------------------------------------------------------
@v1.post("/predict/batch", response_model=APIResponse)
async def predict_batch(req: BatchRequest, request: Request):
    """Bulk prediction for multiple artist pairs.

    Processes up to 1000 pairs per request.
    Returns probability for each pair.
    """
    start = time.time()
    model, version = registry.get_logit(req.model_version)

    from features.pipeline_links import build_link_prediction_embeddings_from_artist_list

    results = []
    pairs = []
    for pair in req.pairs:
        try:
            src_int = _resolve_artist(pair.src)
            dst_int = _resolve_artist(pair.dst)
            pairs.append((src_int, dst_int))
        except HTTPException:
            results.append(BatchResultItem(src=pair.src, dst=pair.dst, probability=-1.0))

    if pairs:
        embeddings = build_link_prediction_embeddings_from_artist_list(pairs)
        X = embeddings[_LOGIT_FEATURES].values
        probs = model.predict_proba(X)
        if probs.ndim > 1 and probs.shape[1] > 1:
            probs = probs[:, 1]
        probs = np.clip(probs, 0.0, 0.99)

        for i, (src_int, dst_int) in enumerate(pairs):
            prob = float(probs[i])
            observe_prediction(prob, version)
            results.append(BatchResultItem(
                src=str(src_int),
                dst=str(dst_int),
                probability=prob,
            ))

    return APIResponse(
        data=BatchData(results=results),
        meta=_build_meta(version, (time.time() - start) * 1000, False, request),
    )


# ---------------------------------------------------------------
# POST /api/v1/predict/compare  (Strategy 4.2 - A/B testing)
# ---------------------------------------------------------------
@v1.post("/predict/compare", response_model=APIResponse)
async def predict_compare(req: CompareRequest, request: Request):
    """Compare predictions across multiple model versions (A/B testing).

    This directly supports Strategy 4.2: 'A/B test PU learning vs standard logistic regression'.
    Send the same artist pair to multiple model versions and compare outputs.
    """
    from features.pipeline_links import build_link_prediction_embeddings_from_artist_list

    src_int = _resolve_artist(req.src_artist)
    dst_int = _resolve_artist(req.dst_artist)

    embeddings = build_link_prediction_embeddings_from_artist_list([(src_int, dst_int)])
    X = embeddings[_LOGIT_FEATURES].values

    results = []
    for ver in req.versions:
        t0 = time.time()
        try:
            model, actual_ver = registry.get_logit(ver)
            probs = model.predict_proba(X)
            if probs.ndim > 1 and probs.shape[1] > 1:
                probs = probs[:, 1]
            probs = np.clip(probs, 0.0, 0.99)
            prob = float(probs[0])
        except ValueError as e:
            prob = -1.0
            actual_ver = ver
        elapsed = (time.time() - t0) * 1000

        results.append(CompareResultItem(
            version=actual_ver,
            probability=prob,
            latency_ms=round(elapsed, 2),
        ))

    return APIResponse(
        data=CompareData(
            src_artist=req.src_artist,
            dst_artist=req.dst_artist,
            results=results,
        ),
        meta=_build_meta("compare", 0, False, request),
    )


# ---------------------------------------------------------------
# POST /api/v1/generate/tracks
# ---------------------------------------------------------------
@v1.post("/generate/tracks", response_model=APIResponse)
async def generate_tracks(req: TrackGenRequest, request: Request):
    """Generate synthetic track features for an artist pair using the CVAE.

    Uses the CVAE model registry for plug-and-play version selection.
    """
    start = time.time()

    src_int = _resolve_artist(req.src_artist)
    dst_int = _resolve_artist(req.dst_artist)
    cvae_ver = req.model_version or "v1"

    # Check for existing tracks first (version-aware)
    from app import check_existing_synthetic_tracks, generate_synthetic_tracks
    existing = check_existing_synthetic_tracks(str(src_int), str(dst_int), limit=req.num_tracks, cvae_version=cvae_ver)

    if existing:
        observe_cache("synthetic_tracks", True)
        tracks = [SyntheticTrackItem(track_id=tid, features={}) for tid, _ in existing]
        # Get probability from existing predictions
        conn = get_pg_conn()
        q = "SELECT prob FROM prediction_connections WHERE src::int = %s AND dst::int = %s LIMIT 1"
        df = pd.read_sql_query(q, conn, params=(src_int, dst_int))
        conn.close()
        prob = float(df["prob"].iloc[0]) if not df.empty else 0.0

        return APIResponse(
            data=TrackGenData(
                src_artist=req.src_artist,
                dst_artist=req.dst_artist,
                probability=prob,
                tracks=tracks,
            ),
            meta=_build_meta(req.model_version or "cvae_v1", (time.time() - start) * 1000, True, request),
        )

    observe_cache("synthetic_tracks", False)

    # Need to generate: first predict link, then generate tracks
    logit_model, logit_ver = registry.get_logit()
    logit_model_id = LOGIT_VERSION_TO_ID.get(logit_ver, 5)
    from features.pipeline_links import build_link_prediction_embeddings_from_artist_list

    embeddings = build_link_prediction_embeddings_from_artist_list([(src_int, dst_int)])
    X = embeddings[_LOGIT_FEATURES].values
    probs = logit_model.predict_proba(X)
    if probs.ndim > 1 and probs.shape[1] > 1:
        probs = probs[:, 1]
    probs = np.clip(probs, 0.0, 0.99)
    prob = float(probs[0])

    embeddings["prob"] = prob

    from app import save_predictions_to_db
    pred_df = pd.DataFrame({"src": [src_int], "dst": [dst_int], "prob": [prob]})
    save_predictions_to_db(pred_df, model_id=logit_model_id)

    track_ids = generate_synthetic_tracks(
        cvae_version=cvae_ver,
        df_pred_links=embeddings,
        limit=req.num_tracks,
    )

    tracks = [SyntheticTrackItem(track_id=tid, features={}) for tid in track_ids]

    return APIResponse(
        data=TrackGenData(
            src_artist=req.src_artist,
            dst_artist=req.dst_artist,
            probability=prob,
            tracks=tracks,
        ),
        meta=_build_meta(req.model_version or "cvae_v1", (time.time() - start) * 1000, False, request),
    )


# ---------------------------------------------------------------
# POST /api/v1/generate/playlist
# ---------------------------------------------------------------
@v1.post("/generate/playlist", response_model=APIResponse)
async def generate_playlist(req: PlaylistRequest, request: Request):
    """Find real tracks similar to synthetic tracks via Aitchison distance.

    Wraps the existing /ml/synthetic-tracks-similarity logic with the v1 schema.
    """
    start = time.time()

    from models.track_similarity import TrackSimilarity
    from pydantic import BaseModel, Field
    from typing import List

    # Build the request object that TrackSimilarity expects
    class _InternalReq:
        def __init__(self, input_tracks, num_similar_tracks):
            self.input_tracks = input_tracks
            self.num_similar_tracks = num_similar_tracks

    internal_req = _InternalReq(req.synthetic_track_ids, req.num_similar)

    try:
        t = TrackSimilarity(internal_req)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Track similarity failed: {e}")

    similar = []
    for _, nbr_scores in t.sorted_genre_scores.items():
        count = 0
        for track_id, score in nbr_scores:
            # Get recording name
            conn = get_pg_conn()
            q = "SELECT name FROM recording WHERE id = %s::int"
            df = pd.read_sql_query(q, conn, params=(track_id,))
            conn.close()
            tname = str(df["name"].iloc[0]) if not df.empty else "Unknown"

            from app import get_artists_from_tracks
            artists = get_artists_from_tracks([track_id])
            artist1 = str(artists.name1.iloc[0]) if not artists.empty else "Unknown"
            artist2 = str(artists.name2.iloc[0]) if not artists.empty else ""

            similar.append(SimilarTrackItem(
                recording_name=tname,
                artist_name=artist1,
                artist_name_2=artist2,
                similarity=score,
            ))
            count += 1
            if count >= req.num_similar:
                break

    PLAYLIST_CREATIONS.inc()

    return APIResponse(
        data=PlaylistData(similar_tracks=similar),
        meta=_build_meta("", (time.time() - start) * 1000, False, request),
    )


# ---------------------------------------------------------------
# GET /api/v1/artist/{artist_id}/profile
# ---------------------------------------------------------------
@v1.get("/artist/{artist_id}/profile", response_model=APIResponse)
async def artist_profile(artist_id: str, request: Request):
    """Comprehensive artist profile combining all data sources.

    Aggregates: MusicBrainz metadata, LastFM popularity, genre proportions,
    collaboration count, top collaborators, embedding availability.
    """
    start = time.time()

    artist_int = _resolve_artist(artist_id)
    conn = get_pg_conn()

    # Basic info
    q_basic = """
        SELECT a.id, a.gid, a.name
        FROM artist a WHERE a.id = %s
    """
    df_basic = pd.read_sql_query(q_basic, conn, params=(artist_int,))
    if df_basic.empty:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Artist not found: {artist_id}")

    name = str(df_basic["name"].iloc[0])
    mbid = str(df_basic["gid"].iloc[0])

    # Spotify ID
    q_spotify = "SELECT spotify_id FROM artist_mbid_spotify WHERE artist_mbid = %s::uuid LIMIT 1"
    df_spot = pd.read_sql_query(q_spotify, conn, params=(mbid,))
    spotify_id = str(df_spot["spotify_id"].iloc[0]) if not df_spot.empty else None

    # Popularity
    q_pop = "SELECT popularity FROM lastfm_artist_stats WHERE artist_id = %s LIMIT 1"
    df_pop = pd.read_sql_query(q_pop, conn, params=(artist_int,))
    popularity = float(df_pop["popularity"].iloc[0]) if not df_pop.empty else None

    # Genre distribution
    q_genre = """
        SELECT * FROM artist_genre_proportions WHERE artist_id = %s LIMIT 1
    """
    df_genre = pd.read_sql_query(q_genre, conn, params=(artist_int,))
    genre_dist = {}
    if not df_genre.empty:
        genre_cols = [c for c in df_genre.columns if c != "artist_id"]
        for c in genre_cols:
            val = float(df_genre[c].iloc[0])
            if val > 0.01:
                genre_dist[c] = round(val, 4)

    # Collab count + top collabs
    q_collabs = """
        SELECT a2.gid AS mbid, a2.name, COUNT(*) AS collab_count
        FROM artist_collab ac
        JOIN artist a2 ON ac.neighbor_artist_id = a2.id
        WHERE ac.artist_id = %s
        GROUP BY a2.gid, a2.name
        ORDER BY collab_count DESC
        LIMIT 10
    """
    df_collabs = pd.read_sql_query(q_collabs, conn, params=(artist_int,))
    total_collabs = 0
    q_total = "SELECT COUNT(*) AS cnt FROM artist_collab WHERE artist_id = %s"
    df_total = pd.read_sql_query(q_total, conn, params=(artist_int,))
    if not df_total.empty:
        total_collabs = int(df_total["cnt"].iloc[0])

    top_collabs = []
    for _, row in df_collabs.iterrows():
        top_collabs.append({
            "mbid": str(row["mbid"]),
            "name": str(row["name"]),
            "collab_count": int(row["collab_count"]),
        })

    # Embedding availability
    q_emb = "SELECT 1 FROM artist_embeddings_n2v WHERE artist_id = %s LIMIT 1"
    df_emb = pd.read_sql_query(q_emb, conn, params=(artist_int,))
    has_embedding = not df_emb.empty

    conn.close()

    return APIResponse(
        data=ArtistProfileData(
            name=name,
            artist_id=artist_int,
            mbid=mbid,
            spotify_id=spotify_id,
            popularity=popularity,
            genre_distribution=genre_dist,
            collab_count=total_collabs,
            top_collabs=top_collabs,
            embedding_available=has_embedding,
        ),
        meta=_build_meta("", (time.time() - start) * 1000, False, request),
    )


# ---------------------------------------------------------------
# POST /api/v1/feedback  (Strategy 4.2 - model improvement)
# ---------------------------------------------------------------
@v1.post("/feedback", response_model=APIResponse)
async def submit_feedback(req: FeedbackRequest, request: Request):
    """Submit feedback on a prediction for model improvement.

    Supports Strategy 4.2: 'Implement online learning for prediction feedback'.
    Collected feedback enables future model retraining on user signal.
    """
    user = getattr(request.state, "user", None)
    user_id = user["user_id"] if user and isinstance(user, dict) else None

    src_int = _resolve_artist(req.prediction_src)
    dst_int = _resolve_artist(req.prediction_dst)

    conn = get_pg_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO prediction_feedback
               (user_id, prediction_src, prediction_dst, rating, comment)
               VALUES (%s, %s, %s, %s, %s)""",
            (user_id, src_int, dst_int, req.rating, req.comment),
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=f"Failed to save feedback: {e}")
    conn.close()

    FEEDBACK_SUBMISSIONS.inc()

    return APIResponse(
        data={"status": "received", "rating": req.rating},
        meta=_build_meta("", 0, False, request),
    )


# ===============================================================
# Phase 2 Endpoints
# ===============================================================


# ---------------------------------------------------------------
# POST /api/v1/explore/what-if
# ---------------------------------------------------------------
@v1.post("/explore/what-if", response_model=APIResponse)
async def explore_what_if(req: WhatIfRequest, request: Request):
    """'What would happen if X and Y collaborated?' scenario explorer.

    For each unique artist pair:
    1. Checks scenario_cache for full cached result
    2. Checks prediction_connections for stored probability (version-aware)
    3. Checks synthetic_tracks for existing CVAE output (version-aware)
    4. Runs Aitchison similarity to find matching real tracks
    5. Persists all intermediate results to shared DB tables
    """
    import hashlib
    import json as _json
    from itertools import combinations

    start = time.time()

    if len(req.artists) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 artists")

    # Resolve all artists
    resolved = []
    for raw in req.artists:
        artist_int = _resolve_artist(raw)
        resolved.append((raw, artist_int))

    # Generate unique pairs
    pairs = list(combinations(resolved, 2))

    model, version = registry.get_logit(req.model_version)
    model_id = LOGIT_VERSION_TO_ID.get(version, 5)
    cvae_ver = req.model_version or "v1"
    scenario_dict = req.scenario.model_dump() if req.scenario else {}

    from app import (
        check_prediction_connections,
        check_existing_synthetic_tracks,
        save_predictions_to_db,
        generate_synthetic_tracks,
    )

    results = []
    for (raw_a, id_a), (raw_b, id_b) in pairs:
        src_int, dst_int = min(id_a, id_b), max(id_a, id_b)
        src_name = _get_name_from_id(src_int)
        dst_name = _get_name_from_id(dst_int)

        # --- LAYER 1: Check scenario_cache ---
        cache_payload = _json.dumps({"pair": [src_int, dst_int], "scenario": scenario_dict}, sort_keys=True)
        cache_key = hashlib.sha256(cache_payload.encode()).hexdigest()

        conn = get_pg_conn()
        q = """SELECT result FROM scenario_cache
               WHERE cache_key = %s AND expires_at > NOW() LIMIT 1"""
        df_cache = pd.read_sql_query(q, conn, params=(cache_key,))
        conn.close()

        if not df_cache.empty:
            observe_cache("scenario", True)
            cached_result = df_cache["result"].iloc[0]
            if isinstance(cached_result, str):
                cached_result = _json.loads(cached_result)
            results.append(WhatIfPairResult(**cached_result))
            continue

        observe_cache("scenario", False)

        # --- LAYER 2: Check prediction_connections (version-aware) ---
        has_pred = check_prediction_connections(str(src_int), str(dst_int), model_id=model_id)
        if has_pred:
            observe_cache("prediction", True)
            conn = get_pg_conn()
            q = """SELECT prob FROM prediction_connections
                   WHERE src::int = %s AND dst::int = %s AND model_id = %s LIMIT 1"""
            df_prob = pd.read_sql_query(q, conn, params=(src_int, dst_int, model_id))
            conn.close()
            prob = float(df_prob["prob"].iloc[0]) if not df_prob.empty else 0.0
        else:
            observe_cache("prediction", False)
            from features.pipeline_links import build_link_prediction_embeddings_from_artist_list
            embeddings = build_link_prediction_embeddings_from_artist_list([(src_int, dst_int)])
            X = embeddings[_LOGIT_FEATURES].values
            probs = model.predict_proba(X)
            if probs.ndim > 1 and probs.shape[1] > 1:
                probs = probs[:, 1]
            probs = np.clip(probs, 0.0, 0.99)
            prob = float(probs[0])

            pred_df = pd.DataFrame({"src": [src_int], "dst": [dst_int], "prob": [prob]})
            save_predictions_to_db(pred_df, model_id=model_id)

        observe_prediction(prob, version)

        # --- LAYER 3: Check synthetic_tracks (version-aware) ---
        existing = check_existing_synthetic_tracks(str(src_int), str(dst_int), limit=req.num_tracks, cvae_version=cvae_ver)

        if existing:
            observe_cache("synthetic_tracks", True)
            track_ids = [tid for tid, _ in existing]
        else:
            observe_cache("synthetic_tracks", False)
            if not has_pred:
                # embeddings already built above
                embeddings["prob"] = prob
            else:
                from features.pipeline_links import build_link_prediction_embeddings_from_artist_list
                embeddings = build_link_prediction_embeddings_from_artist_list([(src_int, dst_int)])
                embeddings["prob"] = prob

            track_ids = generate_synthetic_tracks(
                cvae_version=cvae_ver,
                df_pred_links=embeddings,
                limit=req.num_tracks,
            )

        synth_tracks = [{"track_id": tid} for tid in track_ids]

        # --- LAYER 4: Aitchison similarity ---
        similar_real = []
        if track_ids:
            try:
                from models.track_similarity import TrackSimilarity

                class _InternalReq:
                    def __init__(self, input_tracks, num_similar_tracks):
                        self.input_tracks = input_tracks
                        self.num_similar_tracks = num_similar_tracks

                t = TrackSimilarity(_InternalReq(track_ids, req.num_similar))
                for _, nbr_scores in t.sorted_genre_scores.items():
                    count = 0
                    for rec_id, score in nbr_scores:
                        conn = get_pg_conn()
                        q = "SELECT name FROM recording WHERE id = %s::int"
                        df_rec = pd.read_sql_query(q, conn, params=(rec_id,))
                        conn.close()
                        rec_name = str(df_rec["name"].iloc[0]) if not df_rec.empty else "Unknown"

                        from app import get_artists_from_tracks
                        artists = get_artists_from_tracks([rec_id])
                        a1 = str(artists.name1.iloc[0]) if not artists.empty else "Unknown"
                        a2 = str(artists.name2.iloc[0]) if not artists.empty else ""

                        similar_real.append({
                            "recording_name": rec_name,
                            "artist_name": a1,
                            "artist_name_2": a2,
                            "similarity": score,
                        })
                        count += 1
                        if count >= req.num_similar:
                            break
            except Exception as e:
                print(f"[what-if] Aitchison similarity error: {e}")

        pair_result = WhatIfPairResult(
            src_artist=str(src_int),
            src_name=src_name,
            dst_artist=str(dst_int),
            dst_name=dst_name,
            probability=prob,
            synthetic_tracks=synth_tracks,
            similar_real_tracks=similar_real,
        )
        results.append(pair_result)

        # --- PERSIST: Save full result to scenario_cache ---
        conn = get_pg_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                """INSERT INTO scenario_cache (cache_key, result, expires_at)
                   VALUES (%s, %s::jsonb, NOW() + INTERVAL '7 days')
                   ON CONFLICT (cache_key) DO UPDATE
                   SET result = EXCLUDED.result, expires_at = EXCLUDED.expires_at""",
                (cache_key, _json.dumps(pair_result.model_dump())),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[what-if] Cache write error: {e}")
        conn.close()

    return APIResponse(
        data=WhatIfData(scenarios=results),
        meta=_build_meta(version, (time.time() - start) * 1000, False, request),
    )


# ---------------------------------------------------------------
# GET /api/v1/trends/daily
# ---------------------------------------------------------------
@v1.get("/trends/daily", response_model=APIResponse)
async def daily_trends(request: Request, date: str = None, genre: str = None, limit: int = 5):
    """Return pre-computed daily featured predictions.

    Data is populated by the daily scheduler via POST /api/v1/internal/populate-daily.
    """
    from datetime import date as date_type

    start = time.time()
    if not date:
        date = str(date_type.today())

    conn = get_pg_conn()
    if genre:
        q = """SELECT src_artist_id, src_artist_name, dst_artist_id, dst_artist_name,
                      probability, genre, synthetic_track_ids
               FROM daily_predictions
               WHERE prediction_date = %s AND genre = %s
               ORDER BY probability DESC LIMIT %s"""
        df = pd.read_sql_query(q, conn, params=(date, genre, limit))
    else:
        q = """SELECT src_artist_id, src_artist_name, dst_artist_id, dst_artist_name,
                      probability, genre, synthetic_track_ids
               FROM daily_predictions
               WHERE prediction_date = %s
               ORDER BY probability DESC LIMIT %s"""
        df = pd.read_sql_query(q, conn, params=(date, limit))
    conn.close()

    connections = []
    for _, row in df.iterrows():
        track_ids = row.get("synthetic_track_ids") or []
        if isinstance(track_ids, str):
            track_ids = [int(x) for x in track_ids.strip("{}").split(",") if x]
        connections.append(FeaturedConnection(
            src_artist_name=str(row["src_artist_name"]),
            dst_artist_name=str(row["dst_artist_name"]),
            src_artist_id=int(row["src_artist_id"]),
            dst_artist_id=int(row["dst_artist_id"]),
            probability=float(row["probability"]),
            genre=str(row["genre"]),
            synthetic_track_ids=track_ids,
        ))

    return APIResponse(
        data=DailyTrendsData(date=date, featured_connections=connections),
        meta=_build_meta("", (time.time() - start) * 1000, True, request),
    )


# ---------------------------------------------------------------
# POST /api/v1/internal/populate-daily  (Go scheduler calls this)
# ---------------------------------------------------------------
@v1.post("/internal/populate-daily", response_model=APIResponse)
async def populate_daily(request: Request):
    """Populate daily_predictions table. Called by the Go scheduler.

    For each genre, picks top artists, samples pairs, runs the DB-first
    predict+generate pipeline, and stores results in daily_predictions
    and the shared prediction_connections / synthetic_tracks tables.
    """
    import random
    from datetime import date as date_type
    from itertools import combinations as combos

    # Only allow internal service calls
    user = getattr(request.state, "user", None)
    if not user or user.get("tier") != "internal":
        raise HTTPException(status_code=403, detail="Internal endpoint only")

    start = time.time()
    today = str(date_type.today())

    model, version = registry.get_logit()
    model_id = LOGIT_VERSION_TO_ID.get(version, 5)
    cvae_ver = "v1"

    from app import (
        check_prediction_connections,
        check_existing_synthetic_tracks,
        save_predictions_to_db,
        generate_synthetic_tracks,
    )

    genres = [
        "rock", "pop", "hip hop", "jazz", "classical", "electronic",
        "r&b", "country", "metal", "folk", "punk", "blues",
    ]

    rows_inserted = 0
    genres_processed = 0

    for genre in genres:
        # Get top artists in this genre
        conn = get_pg_conn()
        q = """SELECT artist_id FROM artist_genre_proportions
               WHERE genre = %s ORDER BY proportion DESC LIMIT 50"""
        try:
            df_artists = pd.read_sql_query(q, conn, params=(genre,))
        except Exception:
            # genre column might not exist as a filter — try broader query
            df_artists = pd.DataFrame()
        conn.close()

        if df_artists.empty or len(df_artists) < 2:
            continue

        artist_ids = df_artists["artist_id"].tolist()
        sample_size = min(5, len(list(combos(artist_ids[:20], 2))))
        pairs = random.sample(list(combos(artist_ids[:20], 2)), sample_size)

        for src_int, dst_int in pairs:
            src_name = _get_name_from_id(src_int)
            dst_name = _get_name_from_id(dst_int)

            # DB-first: check prediction_connections
            has_pred = check_prediction_connections(str(src_int), str(dst_int), model_id=model_id)
            if has_pred:
                conn = get_pg_conn()
                q = """SELECT prob FROM prediction_connections
                       WHERE src::int = %s AND dst::int = %s AND model_id = %s LIMIT 1"""
                df_prob = pd.read_sql_query(q, conn, params=(src_int, dst_int, model_id))
                conn.close()
                prob = float(df_prob["prob"].iloc[0]) if not df_prob.empty else 0.0
            else:
                from features.pipeline_links import build_link_prediction_embeddings_from_artist_list
                embeddings = build_link_prediction_embeddings_from_artist_list([(src_int, dst_int)])
                X = embeddings[_LOGIT_FEATURES].values
                probs = model.predict_proba(X)
                if probs.ndim > 1 and probs.shape[1] > 1:
                    probs = probs[:, 1]
                probs = np.clip(probs, 0.0, 0.99)
                prob = float(probs[0])
                pred_df = pd.DataFrame({"src": [src_int], "dst": [dst_int], "prob": [prob]})
                save_predictions_to_db(pred_df, model_id=model_id)

            # DB-first: check synthetic_tracks
            existing = check_existing_synthetic_tracks(str(src_int), str(dst_int), limit=5, cvae_version=cvae_ver)
            if existing:
                track_ids = [tid for tid, _ in existing]
            else:
                if not has_pred:
                    embeddings["prob"] = prob
                else:
                    from features.pipeline_links import build_link_prediction_embeddings_from_artist_list
                    embeddings = build_link_prediction_embeddings_from_artist_list([(src_int, dst_int)])
                    embeddings["prob"] = prob
                track_ids = generate_synthetic_tracks(
                    cvae_version=cvae_ver,
                    df_pred_links=embeddings,
                    limit=5,
                )

            # Insert into daily_predictions
            conn = get_pg_conn()
            cur = conn.cursor()
            try:
                cur.execute(
                    """INSERT INTO daily_predictions
                       (prediction_date, genre, src_artist_id, src_artist_name,
                        dst_artist_id, dst_artist_name, probability, synthetic_track_ids)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (prediction_date, genre, src_artist_id, dst_artist_id)
                       DO UPDATE SET probability = EXCLUDED.probability,
                                     synthetic_track_ids = EXCLUDED.synthetic_track_ids""",
                    (today, genre, src_int, src_name, dst_int, dst_name, prob, track_ids),
                )
                conn.commit()
                rows_inserted += 1
            except Exception as e:
                conn.rollback()
                print(f"[populate-daily] Insert error for {genre}/{src_int}-{dst_int}: {e}")
            conn.close()

        genres_processed += 1

    return APIResponse(
        data={"rows_inserted": rows_inserted, "genres_processed": genres_processed},
        meta=_build_meta(version, (time.time() - start) * 1000, False, request),
    )


# ---------------------------------------------------------------
# GET /api/v1/dataset/export
# ---------------------------------------------------------------
@v1.get("/dataset/export")
async def dataset_export(request: Request, format: str = "csv", genre: str = None,
                         min_probability: float = 0.0, max_probability: float = 1.0,
                         limit: int = 10000, model_version: str = None):
    """Export prediction data as CSV or Parquet.

    Access: admin or researcher/enterprise tiers only.
    Free-tier users are blocked unless they are admin.
    """
    from fastapi.responses import StreamingResponse
    from middleware.metrics import DATASET_EXPORTS
    import io

    start = time.time()

    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    tier = user.get("tier", "free")
    email = user.get("email", "")
    is_admin = email == "admin@interlude.local" or tier == "internal"

    # Tier gate
    if tier == "free" and not is_admin:
        raise HTTPException(
            status_code=403,
            detail="Export requires Researcher tier or above. Upgrade at /api/v1/auth/upgrade",
        )

    # Demo tier: 100 rows max, 10 exports max per key
    if tier == "demo":
        limit = min(limit, 100)
        # Check export count for this demo user
        user_id = user.get("user_id")
        conn = get_pg_conn()
        q = "SELECT COUNT(*) AS cnt FROM dataset_exports WHERE user_id = %s::uuid"
        df_cnt = pd.read_sql_query(q, conn, params=(user_id,))
        conn.close()
        export_count = int(df_cnt["cnt"].iloc[0]) if not df_cnt.empty else 0
        if export_count >= 10:
            raise HTTPException(
                status_code=429,
                detail="Demo export limit reached (10 exports per key). Register for a free account to continue.",
            )

    # Cap limits by tier
    if tier == "researcher" and not is_admin:
        limit = min(limit, 100000)

    # Resolve model_id for version filter
    if model_version:
        mid = LOGIT_VERSION_TO_ID.get(model_version)
        if not mid:
            raise HTTPException(status_code=400, detail=f"Unknown model version: {model_version}")
    else:
        mid = LOGIT_VERSION_TO_ID.get(registry.list_available()["logit"]["default"], 5)

    # Query shared prediction_connections table
    conn = get_pg_conn()
    if genre:
        q = """
            SELECT pc.src, a1.name AS src_name, a1.gid AS src_mbid,
                   pc.dst, a2.name AS dst_name, a2.gid AS dst_mbid,
                   pc.prob, pc.model_id,
                   COALESCE(st.track_count, 0) AS synthetic_track_count
            FROM prediction_connections pc
            JOIN artist a1 ON a1.id = pc.src::int
            JOIN artist a2 ON a2.id = pc.dst::int
            LEFT JOIN (
                SELECT src_artist_id, dst_artist_id, COUNT(*) AS track_count
                FROM synthetic_tracks GROUP BY src_artist_id, dst_artist_id
            ) st ON st.src_artist_id = pc.src::int AND st.dst_artist_id = pc.dst::int
            WHERE pc.prob BETWEEN %s AND %s
              AND pc.model_id = %s
              AND EXISTS (
                  SELECT 1 FROM artist_genre_proportions agp
                  WHERE agp.artist_id = pc.src::int AND agp.genre = %s
              )
            ORDER BY pc.prob DESC LIMIT %s
        """
        df = pd.read_sql_query(q, conn, params=(min_probability, max_probability, mid, genre, limit))
    else:
        q = """
            SELECT pc.src, a1.name AS src_name, a1.gid AS src_mbid,
                   pc.dst, a2.name AS dst_name, a2.gid AS dst_mbid,
                   pc.prob, pc.model_id,
                   COALESCE(st.track_count, 0) AS synthetic_track_count
            FROM prediction_connections pc
            JOIN artist a1 ON a1.id = pc.src::int
            JOIN artist a2 ON a2.id = pc.dst::int
            LEFT JOIN (
                SELECT src_artist_id, dst_artist_id, COUNT(*) AS track_count
                FROM synthetic_tracks GROUP BY src_artist_id, dst_artist_id
            ) st ON st.src_artist_id = pc.src::int AND st.dst_artist_id = pc.dst::int
            WHERE pc.prob BETWEEN %s AND %s
              AND pc.model_id = %s
            ORDER BY pc.prob DESC LIMIT %s
        """
        df = pd.read_sql_query(q, conn, params=(min_probability, max_probability, mid, limit))
    conn.close()

    # Log to dataset_exports audit table
    user_id = user.get("user_id")
    conn = get_pg_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO dataset_exports (user_id, filters, row_count, file_format)
               VALUES (%s::uuid, %s::jsonb, %s, %s)""",
            (user_id, _json_dumps_safe({
                "genre": genre, "min_prob": min_probability,
                "max_prob": max_probability, "model_version": model_version,
            }), len(df), format),
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[export] Audit log error: {e}")
    conn.close()

    DATASET_EXPORTS.inc()

    if format == "parquet":
        buf = io.BytesIO()
        df.to_parquet(buf, index=False, engine="pyarrow")
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/octet-stream",
            headers={"Content-Disposition": "attachment; filename=interlude_predictions.parquet"},
        )
    else:
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=interlude_predictions.csv"},
        )


def _json_dumps_safe(obj):
    """JSON serialize for psycopg2 params."""
    import json as _json
    return _json.dumps(obj)


# ---------------------------------------------------------------
# POST /api/v1/internal/upgrade-tier  (Stripe webhook calls this)
# ---------------------------------------------------------------
@v1.post("/internal/upgrade-tier", response_model=APIResponse)
async def upgrade_tier(req: UpgradeTierRequest, request: Request):
    """Upgrade an API user's tier. Called by Go stripeWebhookHandler.

    Internal endpoint only (X-Internal-Secret auth).
    """
    user = getattr(request.state, "user", None)
    if not user or user.get("tier") != "internal":
        raise HTTPException(status_code=403, detail="Internal endpoint only")

    tier_limits = {"free": 100, "researcher": 1000, "enterprise": 10000}
    new_limit = tier_limits.get(req.tier, 100)

    conn = get_pg_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE api_users SET tier = %s, rate_limit_per_hour = %s
               WHERE email = %s""",
            (req.tier, new_limit, req.email),
        )
        if cur.rowcount == 0:
            conn.close()
            raise HTTPException(status_code=404, detail=f"No API user with email: {req.email}")
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=f"Tier update failed: {e}")
    conn.close()

    return APIResponse(
        data={"email": req.email, "tier": req.tier, "rate_limit_per_hour": new_limit},
        meta=_build_meta("", 0, False, request),
    )
