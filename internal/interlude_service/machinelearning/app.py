# ml_service/app.py
""" This is the API service that connects the python model implementation to the GO frontend"""

from random import random
from fastapi import FastAPI, HTTPException
import numpy
import numpy
from pydantic import BaseModel, Field
from typing import List, Optional
import time

from models.track_similarity import TrackSimilarity
from models.track_feature_predictor import (
    load_cvae_artifact,
    generate_for_rows, 
    C_COLS,
    Y_CONT_COLS,
    Y_BIN_COLS,
    get_pg_conn
)

from scipy.fftpack import dst
from utils import database,metrics
import pandas as pd
from features.pipeline_links import (
    get_artist_k_neighbors_full_random,
    build_embedding_lookup,
    build_neighbors_dict,
    build_features_for_pairs
)
from utils.database import get_pg_conn
import warnings
from config.config import (
    CVAE_ARTIFACT_PATH,
    LOGIT_NUM_PREDICTIONS
)
# Pandas DBAPI warning
warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy connectable",
    category=UserWarning,
)

# sklearn pickle version mismatch warnings
from sklearn.exceptions import InconsistentVersionWarning

warnings.filterwarnings(
    "ignore",
    category=InconsistentVersionWarning,
)

# ============================
# App Initialization
# ============================

app = FastAPI(
    title="Interlude - Artist Collaboration Prediction API",
    version="1.0.0",
    description="""
Predict artist collaborations, generate synthetic tracks,
and discover new music connections.

## Authentication
- **Public endpoints**: `/docs`, `/health`, `/api/v1/models`, `/api/v1/auth/register`
- **API key required**: All `/api/v1/*` endpoints — pass your key in the `X-API-Key` header
- **Legacy endpoints**: `/ml/*` endpoints use existing SDS token auth
- Register for a free key at `POST /api/v1/auth/register`

## Model Versions
All prediction endpoints accept an optional `model_version` parameter.
Available versions: v1, v2, v3, v5 (default). See `GET /api/v1/models`.
""",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ============================
# Middleware — add_middleware prepends, so LAST added = OUTERMOST.
# Execution order: CORS -> Auth -> Metrics -> Handler
# ============================
from middleware.metrics import MetricsMiddleware, metrics_endpoint
from middleware.auth import AuthMiddleware
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(MetricsMiddleware)   # innermost
app.add_middleware(AuthMiddleware)      # middle
app.add_middleware(                     # outermost — handles OPTIONS preflight before auth
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-Request-ID"],
)

# Global exception handler — return actual error message instead of generic 500
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__},
    )

# Prometheus /metrics endpoint
app.add_route("/metrics", metrics_endpoint, methods=["GET"])

# ============================
# v1 API Router
# ============================
from routers.v1 import v1
app.include_router(v1)

# ============================
# Model Registry - preload defaults on startup
# ============================
from models.model_registry import registry

@app.on_event("startup")
async def startup_preload():
    print("[startup] Preloading default models via registry...")
    registry.preload_defaults()
    print("[startup] Model registry ready:", registry.list_available())

# ============================
# Request Schemas
# ============================

class ArtistLinkRequest(BaseModel):
    src_artist_id: str
    dst_artist_id: str
    limit: int = 25
    model_version: str = "logit_v1"


class ArtistNeighborRequest(BaseModel):
    src_artist_id: str
    limit: int = Field(default=25, le=100)
    model_version: str = "logit_v1"


class SyntheticTrackRequest(BaseModel):
    src_artist_id: str
    dst_artist_id: str
    limit: int = Field(default=5, le=25)
    model_version: str = "cvae_v1"
    
class SyntheticTrackSimilarityRequest(BaseModel):
    input_tracks: List[int] # List of synthetic track ids that we want to find similar existing tracks to
    num_similar_tracks: int = Field(default=5, le=250)

class DailyPredictionRequest(BaseModel):
    date: str  # YYYY-MM-DD format
    genre: str = "rock"  # Genre tag to filter artists by
    limit: int = Field(default=10, le=50)
    

""" 
synthetic_track_id_1: [(neighbor_track_id_1, similarity_score_1), (neighbor_track_id_2, similarity_score_2), ...], synthetic_track_id_2: [(neighbor_track_id_3, similarity_score_3), (neighbor_track_id_4, similarity_score_4), ...], ...

}
"""


# ============================
# Response Schemas
# ============================

class ArtistLinkResponse(BaseModel):
    src: List[str]
    dst: List[str]
    probability: List[float]
    model_version: str
    latency_ms: float


class ArtistNeighborPrediction(BaseModel):
    dst_artist_id: str
    probability: float
    tracks: List[int]  # List of synthetic track IDs


class ArtistNeighborResponse(BaseModel):
    src_artist_id: str
    neighbors: List[ArtistNeighborPrediction]
    model_version: str
    latency_ms: float


class SyntheticTrack(BaseModel):
    features: dict
    predicted_popularity: float

class SimilarTrack(BaseModel):
    recording_name: str
    artist_name: str
    artist_name_2: str
    similarity: float

class SyntheticTrackResponse(BaseModel):
    src_artist_id: str
    dst_artist_id: str
    probability: float
    tracks: List[SyntheticTrack]
    model_version: str
    latency_ms: float
    
from pydantic import BaseModel
from typing import List

class NeighborOut(BaseModel):
    name: str
    tracks: list
    probability: float

class ArtistNeighborsResponse(BaseModel):
    name: str
    neighbors: List[NeighborOut]
    model_version: str
    latency_ms: float

class TrackSimilarityResponse(BaseModel):
    similar_tracks: List[SimilarTrack]

class TrackResponse(BaseModel):
    id: str
    name: str
    popularity: Optional[float] = None
    synthetic: bool = False
    
class NeighborResponse(BaseModel):
    name: str
    probability: float
    tracks: List[TrackResponse]

class ArtistNeighborsResponse(BaseModel):
    name: str
    neighbors: List[NeighborResponse]
    model_version: str
    latency_ms: float

class SyntheticTrackSimilarityResponse(BaseModel):
    output_tracks: List[TrackResponse]
    

class DailyPredictionResponse(BaseModel):
    date: str
    genre: str
    src_artist_id: str
    src_artist_name: str
    neighbors: List[ArtistNeighborPrediction]
    model_version: str
    latency_ms: float


# ============================
# Model Loaders (STUBS)
# ============================
from config.config import (
    LOGIT_MODEL_ID,
    LOGIT_MODEL_VERSION,
    MODEL_ENGINEERING_DIR
)
import joblib
from pathlib import Path
def load_logit_model(model_version: str, model_path: str):
    """
    Load the model used to predict probabilities.

    Returns a LinkPredictor instance with a working predict_proba() method.
    """
    from models.link_predictor import LinkPredictor
    path = Path(model_path)
    if not path.exists():
        raise FileNotFoundError(f"Model file not found: {path}")
    return LinkPredictor.load(path)


# def load_cvae_model(model_version: str):
#     # TODO: load from artifacts/
#     return "CVAE_MODEL"


def load_popularity_model():
    # TODO: load regression model
    return "POPULARITY_MODEL"

# ============================
# Embedding Fetch (STUB)
# ============================
    
# def get_artist_embeddings(artist_id: str):
#     """This gets the artist embeddings for individual (src,dst pairs)"""
#     """ Runs the database utility function for single artist embeddings and their metrics required"""
#     df = database.get_artist_embeddings(artist_id)
#     all_artist_ids = df[["src", "dst"]].values.flatten()
#     unique_artists = pd.unique(all_artist_ids)
    
#     conn = get_pg_conn()
#     artist_collab_3 = get_artist_k_neighbors_full_random(conn, unique_artists, k=3)
#     artist_collab_3 = artist_collab_3.rename(
#         columns={
#             artist_collab_3.columns[0]: "src",
#             artist_collab_3.columns[1]: "dst",
#         }
#     )
#     conn.close()
    
#     embeddings = embeddings.loc[:, ~embeddings.columns.duplicated()] #TODO: FIX ROOT PROBLEM OF THIS 
#     embedding_lookup = build_embedding_lookup(embeddings)

#     print("Building neighbors dictionary...")
#     neighbors = build_neighbors_dict(artist_collab_3)

#     print(f"Building features for {len(df)} pairs...")
#     df_features = build_features_for_pairs(
#         pairs_df=df,
#         embedding_lookup=embedding_lookup,
#         neighbors=neighbors,
#         target_col='label',
#         topk=3,
#         verbose=True
#     )
#     print(f"Generated {len(df_features)} feature rows")

#     return df_features.iloc[0] # Only getting the first row because we are only putting one row in, keeping this way so i can debug with breakpoitn here later


# ============================
# Inference Logic (STUBS)
# ============================
from config.config import (
    LINK_PREDICTION_FEATURES
)
from features.pipeline_links import build_link_prediction_embeddings_from_artist_list
def predict_artist_link(model, src_id, dst_id) -> float:
    """ This function is used to predict the src-dst link probability when the user gives us both the src and the dst
    
    INPUTS:
        model: the loaded logit model
        src_id: the source artist id (mbid)
        dst_id: the destination artist id (mbid)    
    OUTPUTS:
        DataFrame 
        COLUMNS: src | dst | prob 
           int(src) | int(dst) | float(probability of link existing)
        
    """
    if type (src_id) == str:
        src = int(get_id_from_mbid(src_id))
    if type (dst_id) == str:
        dst = int(get_id_from_mbid(dst_id))
    if type (src_id) == int:
        src = int(src_id)
    if type (dst_id) == int:
        dst = int(dst_id)

    # TODO: real inference
    # print(f"[DEBUG] predict_artist_link called with src_id={src}, dst_id={dst}")
    # print(f"[DEBUG] src_id type: {type(src)}, dst_id type: {type(dst)}")

    try:
        # print(f"[DEBUG] Building link prediction embeddings for pair: ({src}, {dst})")
        artist_embeddings = build_link_prediction_embeddings_from_artist_list([(src, dst)])
        # print(f"[DEBUG] artist_embeddings shape: {artist_embeddings.shape}")
        # print(f"[DEBUG] artist_embeddings columns: {list(artist_embeddings.columns)}")
        # print(f"[DEBUG] artist_embeddings head:\n{artist_embeddings.head()}")
    except Exception as e:
        # print(f"[ERROR] Failed to build embeddings: {type(e).__name__}: {e}")
        raise e

    try:
        # Use model.feature_names when available so the feature matrix matches
        # what the model was trained on (supports v5, v6, and future versions).
        if hasattr(model, 'feature_names') and model.feature_names is not None:
            _feats = list(model.feature_names)
        else:
            _feats = list(LINK_PREDICTION_FEATURES)
        print(f"[DEBUG] Extracting features: {_feats}")
        X = artist_embeddings[_feats].values
        # print(f"[DEBUG] X shape: {X.shape}")
        # print(f"[DEBUG] X values: {X}")
    except Exception as e:
        # print(f"[ERROR] Failed to extract features: {type(e).__name__}: {e}")
        raise e

    try:
        probs = model.predict_proba(X)
        # LinkPredictor.predict_proba returns 1D (already extracts positive class & clips).
        # Raw sklearn predict_proba returns 2D — extract column 1 in that case.
        if probs.ndim > 1 and probs.shape[1] > 1:
            probs = probs[:, 1]
        probs = numpy.clip(probs, 0.0, 0.99)
    except Exception as e:
        print(f"[ERROR] Failed to predict: {type(e).__name__}: {e}")
        raise e

    # Put back the src - dst pairs
    # print(f"[DEBUG] artist_embeddings shape: {artist_embeddings.shape}")
    res = pd.DataFrame({
        "src": artist_embeddings["src"].values,
        "dst": artist_embeddings["dst"].values,
        "prob": probs,
    })
    # print(f"[DEBUG] Result DataFrame:\n{res}")

    # keep only edges above threshold
    return res

from models.link_predictor import predict_link_features_from_artist, predict_links
def predict_neighbors(model, src_emb: str | int, limit: int):
    """ This function is used to predict the top k neighbors for a given source artist
        This is used when the user only gives us the source artist id (or mbid) and we need to find potential connections
    
    INPUTS:
        model: the loaded logit model
        src_emb: the source artist id or MBID
        limit: number of neighbors to return    
    OUTPUTS:
        List of dicts with dst_artist_id and probability - This is for the frontend compatibility
        AND the full preds dataframe
    """
    # Update: This funciton now creates the link prediction features for the given src artist
    # TODO: score candidate pool
    if type (src_emb) == str:
        src_emb = int(get_id_from_mbid(src_emb))
        print(f"[DEBUG] Converted src_emb to int ID: {src_emb}")

    proportion_of_total = 20  # Using 1/20th of total artists as candidates
    # This will be 582,964 / 20 = 29,148 candidates
    # Use model.feature_names when available so the feature matrix matches
    # what the model was trained on (v5 has 11 features, v6 has 14, etc.).
    if hasattr(model, 'feature_names') and model.feature_names is not None:
        _feats = list(model.feature_names)
    else:
        _feats = list(LINK_PREDICTION_FEATURES)
    preds = predict_link_features_from_artist(model=model,
                                             features=_feats,
                                             THRESHOLD=0.3,
                                             input_artist_id=src_emb,
                                             num_candidates=582964//proportion_of_total,
                                             random_state=67)

    preds = preds.loc[preds.src == src_emb]
    
    # Now to save our predictions to the database
    save_predictions_to_db(preds)
    # And make sure each prediction has a synthetic track created for it in the synthetic_tracks table, we can do this by calling the predict_links function which will create the synthetic tracks for us
    # generate_synthetic_tracks(cvae_version=LOGIT_MODEL_VERSION, df_pred_links=preds, limit=limit)

    return [
        {
            "dst_artist_id": preds.dst.iloc[i],
            "probability": preds.prob.iloc[i],
        }
        for i in range(min(limit, len(preds)))
    ], preds


def check_existing_synthetic_tracks(src: str, dst: str, limit: int = 5, cvae_version: str = None):
    '''Check if there are existing synthetic tracks for a given src-dst artist pair.

    INPUTS:
        src: (str) source artist id
        dst: (str) destination artist id
        limit: (int) number of tracks to check for
        cvae_version: (str) optional CVAE version to filter by (e.g. "v1").
                      If None, returns tracks from any version (legacy behavior).

    OUTPUTS:
        RETURNS A LIST OF THE EXISTING SYNTHETIC TRACK IDS AND THEIR PROBABILITY FROM THE DATABASE
        [(track_id1, prob1), (track_id2, prob2), ...]
        '''

    # Convert to int IDs
    src = int(src)
    dst = int(dst)

    conn = get_pg_conn()
    if cvae_version:
        q = """
            SELECT st.track_id, shlf.prob
            FROM synthetic_tracks st
            JOIN synthetic_tracks_high_level_features shlf
                ON st.track_id = shlf.track_id
            JOIN synthetic_track_model_versions stmv
                ON st.track_id = stmv.track_id
            WHERE st.src_artist_id = %s
            AND st.dst_artist_id = %s
            AND stmv.model_name = 'cvae' AND stmv.version = %s
            ORDER BY shlf.prob DESC
            LIMIT %s;
        """
        df = pd.read_sql_query(q, conn, params=(src, dst, cvae_version, limit))
    else:
        q = """
            SELECT st.track_id, shlf.prob
            FROM synthetic_tracks st
            JOIN synthetic_tracks_high_level_features shlf
                ON st.track_id = shlf.track_id
            WHERE st.src_artist_id = %s
            AND st.dst_artist_id = %s
            ORDER BY shlf.prob DESC
            LIMIT %s;
        """
        df = pd.read_sql_query(q, conn, params=(src, dst, limit))
    conn.close()
    return list(zip(df['track_id'], df['prob']))

def check_existing_synthetic_tracks_from_src(src: any, limit: int = 5):
    """Function to check existing synthetic tracks from src artist to multiple dst artists up to a limit.
    
    INPUTS:
        src: (str or int) source artist id (MBID or int ID)
        limit: (int) number of tracks to check for each dst artist
    OUTPUTS:
        RETURNS A DICTIONARY MAPPING DST ARTIST IDS TO LISTS OF (TRACK_ID, PROBABILITY) TUPLES
        {
            dst_artist_id1: [(track_id1, prob1), (track_id2, prob2), ...],
            dst_artist_id2: [(track_id3, prob3), (track_id4, prob4), ...],
            ...
        }
    """
    # Convert to int ID
    if type(src) == str:  # crude check for MBID length
        src = get_id_from_mbid(src)
    
    src = int(src)
    
    conn = get_pg_conn()
    q = """
        SELECT st.dst_artist_id, st.track_id, shlf.prob
        FROM synthetic_tracks st
        JOIN synthetic_tracks_high_level_features shlf
            ON st.track_id = shlf.track_id
        WHERE st.src_artist_id = %s
        ORDER BY shlf.prob DESC
        LIMIT %s;
    """
    df = pd.read_sql_query(q, conn, params=(src, limit))
    conn.close()
    
    existing_tracks = {}
    for _, row in df.iterrows():
        dst_id = row['dst_artist_id']
        track_id = row['track_id']
        if dst_id not in existing_tracks:
            existing_tracks[dst_id] = []
        existing_tracks[dst_id].append((track_id, row['prob']))
    
    return existing_tracks
    

def generate_synthetic_tracks(cvae_version, 
                              df_pred_links: pd.DataFrame = None, 
                              limit: int = 5, 
                              src: str = None, dst: str = None):
    '''Generates synthetic tracks for a given src-dst artist pair.
    This is the same pipeline as the track_feature_predictor.py file. main function
    
    INPUTS:
        cvae_version: (str) version of the CVAE model to load
        df_pred_links: (pd.DataFrame) DataFrame containing the predicted links between artists in the form of 
            src | dst | prob
        limit: (int) number of tracks that they would create together
        src: (str) source artist id
        dst: (str) destination artist id
        
        
    OUTPUTS: 
        RETURNS A LIST OF THE INSERTED SYNTHETIC TRACK IDS INTO THE DATABASE
        
    THE OUTPUTS WILL BE SAVED TO THE SYNTHTETIC TRACKS TABLE IN THE DATABASE
    '''
    model, prep, meta = load_cvae_artifact(CVAE_ARTIFACT_PATH)
    # print("DEBUG: Loaded CVAE model and prep objects")
    # print("shape of df_pred_links:", df_pred_links.shape)
    yc_samples, yb_probs = generate_for_rows(model,prep,df_pred_links,C_COLS,n_samples = limit) 

    yc_mean = yc_samples.mean(axis=1)
    df_y_cont = pd.DataFrame(yc_mean, columns=Y_CONT_COLS)#, index=df.index)

    if yb_probs is not None:
        yb_mean = yb_probs.mean(axis=1)
        df_y_bin = pd.DataFrame(yb_mean, columns=Y_BIN_COLS, index=df_pred_links.index)
        df_synth = pd.concat([df_pred_links.reset_index(drop=True),
                            df_y_cont.reset_index(drop=True),
                            df_y_bin.reset_index(drop=True)], axis=1)
    else:
        df_synth = pd.concat([df_pred_links.reset_index(drop=True),
                            df_y_cont.reset_index(drop=True)], axis=1)

    # ----- Insert synthetic tracks into database -----
    if not src or not dst:
        src_id = df_pred_links['src'].tolist()
        dst_id = df_pred_links['dst'].tolist()
    else:
        if type(src) == str:
            src = int(get_id_from_mbid(src))
        if type(dst) == str:
            dst = int(get_id_from_mbid(dst))
        
        if type(src) == int:
            src_id = [int(src)]
        if type(dst) == int:
            dst_id = [int(dst)]
    
    from sqlalchemy import create_engine, text
    from config.config import DB_URL

    dsn = DB_URL  # Uses the DSN with search_path options from config.py
    if dsn and dsn.startswith("postgres://"):
        dsn = dsn.replace("postgres://", "postgresql://", 1)

    engine = create_engine(dsn)
    
    all_cols = ["prob"] + Y_CONT_COLS + Y_BIN_COLS
    col_list = ", ".join(all_cols)

    # Bulk insert synthetic tracks using unnest
    st_q = """
    INSERT INTO synthetic_tracks (src_artist_id, dst_artist_id, prediction_id)
    SELECT 
        s.src_id,
        s.dst_id,
        pc.prediction_id
    FROM unnest(:src_ids, :dst_ids) AS s(src_id, dst_id)
    JOIN prediction_connections pc 
        ON pc.src::int = s.src_id 
        AND pc.dst::int = s.dst_id
    ON CONFLICT DO NOTHING
    RETURNING track_id;
    """
    
    hlf_q = f"""
    INSERT INTO synthetic_tracks_high_level_features (track_id, {col_list})
    SELECT
        unnest(:track_ids) AS track_id,
        {', '.join(f'unnest(:{c}) AS {c}' for c in all_cols)}
    ON CONFLICT DO NOTHING
    RETURNING track_id;
    """
    
    model_version_q = """
    INSERT INTO synthetic_track_model_versions (track_id, model_name, version)
    SELECT unnest(:track_ids) AS track_id, 'cvae' AS model_name, :version AS version
    ON CONFLICT DO NOTHING;
    """

    with engine.begin() as conn:
        # Insert synthetic tracks in bulk
        result = conn.execute(text(st_q), {"src_ids": src_id, "dst_ids": dst_id})
        inserted_track_ids = [r.track_id for r in result]

        if not inserted_track_ids:
            print("[WARNING] No tracks were inserted (possibly due to conflicts or limit reached)")
            return []

        # Prepare parameters for high-level features
        num_inserted = len(inserted_track_ids)
        hlf_params = {
            "track_ids": [int(tid) for tid in inserted_track_ids],
            **{c: [float(df_synth.iloc[i][c]) for i in range(num_inserted)] for c in all_cols}
        }
        
        print(f"[DEBUG] Inserting {len(inserted_track_ids)} high-level feature records")
        conn.execute(text(hlf_q), hlf_params)
    
        # Insert model version info in bulk
        model_version_params = {
            "track_ids": inserted_track_ids,
            "version": cvae_version
        }
        conn.execute(text(model_version_q), model_version_params)

    return inserted_track_ids

# ============================
# Patchwork DB Calls
# ============================
def get_recording_name_from_id(recording_id: int) -> str:
    conn = get_pg_conn()
    q = """
        SELECT name
        FROM recording
        WHERE id = %s::int;
    """
    print(f"Getting {recording_id}")

    df = pd.read_sql_query(q, conn, params=(recording_id,))
    conn.close()
    try:
        res = df['name'].iloc[0]
    except KeyError:
        raise("Error with df key",df.head())
    except IndexError:
        raise("Search for recording name from ID not successful, there is no rows in the dataframe")
    
    return res

def get_id_from_mbid(artist_id: str) -> int:
    """ This should only be used for testing, evenutally adjust the code so that it gets ID directly"""
    conn = get_pg_conn()
    q = """
        SELECT id
        FROM artist
        WHERE gid = %s::uuid;
    """
    print(f"Getting {artist_id}")

    df = pd.read_sql_query(q, conn, params=(artist_id,))
    conn.close()
    try:
        res = df['id'].iloc[0]
    except KeyError:
        raise("Error with df key",df.head())
    except IndexError:
        raise("Search for ID from MBID not successful, there is no rows in the dataframe")
    
    return res

def get_mbid_from_id(artist_id: str) -> str:
    """ This should only be used for testing, evenutally adjust the code so that it gets ID directly"""
    conn = get_pg_conn()
    q = """
        SELECT gid
        FROM artist
        WHERE id = %s::int;
    """
    print(f"Getting {artist_id}")

    df = pd.read_sql_query(q, conn, params=(artist_id,))
    conn.close()
    try:
        res = df['gid'].iloc[0]
    except KeyError:
        raise("Error with df key",df.head())
    except IndexError:
        raise("Search for MBID from ID not successful, there is no rows in the dataframe")
    
    return res


def get_name_from_mbid(artist_mbid) -> str:
    """ This should only be used for testing, evenutally adjust the code so that it gets ID directly"""
    conn = get_pg_conn()
    q = """
        SELECT name
        FROM artist
        WHERE gid = %s::uuid;
    """
    print(f"Getting {artist_mbid}")
    q_list = """
        SELECT name
        FROM artist
        WHERE gid = ANY(%s::uuid[]);
    """


    if type(artist_mbid) == list:
        df = pd.read_sql_query(q, conn, params=(artist_mbid,))
        conn.close()
        try:
            res = df['name']
        except KeyError:
            raise("Error with df key",df.head())
        except IndexError:
            raise("Search for ID from MBID not successful, there is no rows in the dataframe")

    df = pd.read_sql_query(q, conn, params=(artist_mbid,))
    conn.close()
    try:
        res = df['name'].iloc[0]
    except KeyError:
        raise("Error with df key",df.head())
    except IndexError:
        raise("Search for ID from MBID not successful, there is no rows in the dataframe")
    
    return res

def get_name_from_id(artist_mbid) -> str:
    """ This should only be used for testing, evenutally adjust the code so that it gets ID directly"""
    conn = get_pg_conn()
    q = """
        SELECT name
        FROM artist
        WHERE id = %s::int;
    """
    print(f"Getting {artist_mbid}")
    q_list = """
        SELECT name
        FROM artist
        WHERE id = ANY(%s::int[]);
    """


    if type(artist_mbid) == list:
        df = pd.read_sql_query(q, conn, params=(artist_mbid,))
        conn.close()
        try:
            res = df['name']
        except KeyError:
            raise("Error with df key",df.head())
        except IndexError:
            raise("Search for ID from MBID not successful, there is no rows in the dataframe")

    df = pd.read_sql_query(q, conn, params=(artist_mbid,))
    conn.close()
    try:
        res = df['name'].iloc[0]
    except KeyError:
        raise("Error with df key",df.head())
    except IndexError:
        raise("Search for ID from MBID not successful, there is no rows in the dataframe")
    
    return res


    
# ============================
# Database Checks Functions
# ============================

def save_predictions_to_db(preds: pd.DataFrame, model_id: int = None):
    """Save the predicted connections to the database.

    This function takes the preds DataFrame which contains src, dst, and prob columns,
    and saves the top predictions to the prediction_connections table in the database.

    INPUTS:
    preds: DataFrame with columns src (int), dst (int), prob (float)
    model_id: (int) model ID to store. Defaults to LOGIT_MODEL_ID for backward compat.
    """
    if model_id is None:
        model_id = LOGIT_MODEL_ID

    conn = get_pg_conn()
    insert_q = """
        INSERT INTO prediction_connections (src, dst, prob, model_id)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (src, dst, model_id) DO UPDATE SET prob = EXCLUDED.prob;
    """
    data_to_insert = [(int(row['src']), int(row['dst']), float(row['prob']), model_id) for _, row in preds.iterrows()]

    with conn.cursor() as cur:
        cur.executemany(insert_q, data_to_insert)
        conn.commit()
    conn.close()

def get_prediction_connections_for_src(src_id: int, limit: int = 25, model_id: int = None) -> pd.DataFrame:
    """Get pre-computed prediction connections for a source artist from the database.

    Queries the prediction_connections table for the top `limit` destination artists
    sorted by probability (descending).

    INPUTS:
        src_id: (int) source artist integer ID
        limit: (int) max number of connections to return
        model_id: (int) model ID to filter by. Defaults to LOGIT_MODEL_ID for backward compat.
    OUTPUTS:
        DataFrame with columns: dst (int), prob (float)
    """
    if model_id is None:
        model_id = LOGIT_MODEL_ID

    conn = get_pg_conn()
    q = """
        SELECT pc.dst, pc.prob
        FROM prediction_connections pc
        WHERE pc.src::int = %s AND pc.model_id = %s
          AND NOT EXISTS (
              SELECT 1 FROM artist_collab ac
              WHERE (ac.artist_id = pc.src::int AND ac.neighbor_artist_id = pc.dst::int)
                 OR (ac.artist_id = pc.dst::int AND ac.neighbor_artist_id = pc.src::int)
          )
        ORDER BY pc.prob DESC
        LIMIT %s;
    """
    df = pd.read_sql_query(q, conn, params=(src_id, model_id, limit))
    conn.close()
    return df

def check_prediction_connections(src: str, dst: str, model_id: int = None):
    """Check if there are existing predicted connections between src and dst artists for a given model.

    INPUTS:
        src: (str) source artist id
        dst: (str) destination artist id
        model_id: (int) integer model ID to filter by. Defaults to LOGIT_MODEL_ID.
    OUTPUTS:
        bool: True if predicted connections exist, False otherwise
    """
    if model_id is None:
        model_id = LOGIT_MODEL_ID

    conn = get_pg_conn()
    q = """
        SELECT COUNT(*) AS connection_count
        FROM prediction_connections
        WHERE ((src::int = %s AND dst::int = %s) OR (src::int = %s AND dst::int = %s))
          AND model_id = %s;
    """
    df = pd.read_sql_query(q, conn, params=(int(src), int(dst), int(dst), int(src), model_id))
    conn.close()
    return df['connection_count'].iloc[0] > 0

def check_existing_link(src: str, dst: str):
    """Check if there is an existing link between src and dst artists in the database.
    
    INPUTS:
        src: (str) source artist id
        dst: (str) destination artist id
    OUTPUTS:
        bool: True if link exists, False otherwise
    """
    conn = get_pg_conn()
    q = """
        SELECT COUNT(*) AS link_count
        FROM artist_collab
        WHERE (artist_id = %s AND neighbor_artist_id = %s)
           OR (artist_id = %s AND neighbor_artist_id = %s);
    """
    df = pd.read_sql_query(q, conn, params=(int(src), int(dst), int(dst), int(src)))
    conn.close()
    return df['link_count'].iloc[0] > 0

def get_synthetic_tracks_from_db(src: str, dst: str, limit: int = 5):
    '''Fetch synthetic tracks for a given src-dst artist pair.
    
    INPUTS:
        src: (str) source artist id
        dst: (str) destination artist id
        limit: (int) number of tracks to fetch
    OUTPUTS: 
        RETURNS A LIST OF THE SYNTHETIC TRACK IDS FROM THE DATABASE
    '''
    
    q = """
        SELECT st.track_id
        FROM synthetic_tracks st
        WHERE st.src_artist_id = %s AND st.dst_artist_id = %s
        LIMIT %s;
        """
    

# ============================
# API Endpoints
# ============================
# artist-link endpoint gets us the probability of a link between two artists
# TODO: Adjust to add the synthetic tracks for the src-dst pair
# artist-neighbors endpoint gets us the top k neighbors for a given artist
# TODO: Adjust to add the synthetic tracks for each neighbor connection
# synthetic-tracks endpoint gets us the synthetic tracks between two artists
@app.post("/ml/predict/artist-link", response_model=ArtistNeighborsResponse)
def predict_artist_link_endpoint(req: ArtistLinkRequest):
    start = time.time()

    if not req.src_artist_id or not req.dst_artist_id:
        raise HTTPException(status_code=404, detail="Missing artist embeddings")
    print("DEBUG PREDICT_ARTIST_LINK")
    print(req.src_artist_id,req.dst_artist_id)

    
    # IF WE CHANGE TO ONLY ARTIST-ID INSTEAD OF MBID, DO THIS
    # src = get_id_from_mbid(req.src_artist_id)
    # dst = get_id_from_mbid(req.dst_artist_id)

    logit_path = os.path.join(MODEL_ENGINEERING_DIR,f'logit_model_{LOGIT_MODEL_VERSION}.joblib')
    pop_model = load_logit_model(f"logit_model_{LOGIT_MODEL_VERSION}",logit_path)

    # RETURNS A DATAFRAME WITH SRC | DST | PROB
    prob = predict_artist_link(pop_model, req.src_artist_id, req.dst_artist_id)
    src,dst = get_id_from_mbid(req.src_artist_id) , get_id_from_mbid(req.dst_artist_id)
    
    # Need to create the context embeddings for the src-dst pair
    p_context = build_link_prediction_embeddings_from_artist_list([(int(src),int(dst))])
    df_pred_links = p_context
    
    df_pred_links['prob'] = prob.prob.values

    # prob is a DataFrame
    neighbors = []
    
    # Now after we have our preds we need to create the synthetic tracks for each neighbor connection
    # This will just be leaded into the database for now
    # Frontend will call the /ml/generate/tracks endpoint to get the tracks for each src-dst pair
    # cvae = load_cvae_model(req.model_version)
    tracks = []
    tracks = check_existing_synthetic_tracks(src=src, dst=dst, limit=req.limit)
    if len(tracks) == 0:
        tracks = generate_synthetic_tracks(cvae_version=req.model_version, df_pred_links=df_pred_links, src=req.src_artist_id, dst=req.dst_artist_id, limit=req.limit)

    for _, row in prob.iterrows():
        neighbors.append({
            "name": str(row["dst"]),
            "tracks": [track for track, prob in tracks],
            "probability": row["prob"]
        })

    return {
        "name": req.src_artist_id,
        "neighbors": neighbors,
        "model_version": req.model_version,
        "latency_ms": (time.time() - start) * 1000
    }
import os
import copy
import numpy as np

@app.post("/ml/predict/artist-neighbors", response_model=ArtistNeighborResponse)
def predict_artist_neighbors_endpoint(req: ArtistNeighborRequest):
    """Predict top k neighbors for a source artist and generate synthetic tracks.

    Flow:
      1. Convert src MBID → int ID
      2. Check prediction_connections table for pre-computed connections
      3. If enough connections found, use them (fast path)
      4. Otherwise fall back to the ML pipeline (slow path)
      5. For each connection, check/create synthetic track features
      6. Return neighbors with track IDs and probabilities
    """
    start = time.time()

    if not req.src_artist_id:
        raise HTTPException(status_code=404, detail="Missing artist embeddings")
    if req.limit <= 0 or req.limit > 100:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 100")

    src = get_id_from_mbid(req.src_artist_id)
    src_int = int(src)

    # ------------------------------------------------------------------
    # STEP 1: Check prediction_connections for pre-computed connections
    # ------------------------------------------------------------------
    pred_connections = get_prediction_connections_for_src(src_int, limit=req.limit)
    print(f"[artist-neighbors] Found {len(pred_connections)} pre-computed connections for src {src_int}")

    if len(pred_connections) >= req.limit:
        # ------- FAST PATH: use pre-computed connections -------
        print(f"[artist-neighbors] Using {req.limit} pre-computed connections (fast path)")
        neighbors = []

        for _, row in pred_connections.iterrows():
            dst_int = int(row['dst'])
            prob = float(row['prob'])

            # Check if synthetic tracks already exist for this pair
            existing_tracks = check_existing_synthetic_tracks(
                src=src_int, dst=dst_int, limit=req.limit
            )
            track_ids = [track_id for track_id, _ in existing_tracks]

            if len(track_ids) == 0:
                # No synthetic tracks yet — generate them
                print(f"[artist-neighbors] Generating synthetic tracks for {src_int} -> {dst_int}")
                pair_list = [(src_int, dst_int)]
                preds_w_context = build_link_prediction_embeddings_from_artist_list(
                    artist_list=pair_list
                )
                preds_w_context['prob'] = prob
                track_ids = generate_synthetic_tracks(
                    cvae_version=req.model_version,
                    df_pred_links=preds_w_context,
                    limit=req.limit,
                )

            dst_mbid = str(get_mbid_from_id(dst_int))
            neighbors.append(ArtistNeighborPrediction(
                dst_artist_id=dst_mbid,
                probability=prob,
                tracks=[int(tid) for tid in track_ids],
            ))

        return ArtistNeighborResponse(
            src_artist_id=req.src_artist_id,
            neighbors=neighbors,
            model_version=req.model_version,
            latency_ms=(time.time() - start) * 1000,
        )

    # ------------------------------------------------------------------
    # STEP 2: FALLBACK — not enough pre-computed connections, run ML pipeline
    # ------------------------------------------------------------------
    print(f"[artist-neighbors] Not enough pre-computed connections ({len(pred_connections)}), falling back to ML pipeline")

    logit_path = os.path.join(MODEL_ENGINEERING_DIR, f'logit_model_{LOGIT_MODEL_VERSION}.joblib')
    pop_model = load_logit_model(f"logit_model_{LOGIT_MODEL_VERSION}", logit_path)
    print("Type of pop_model:", type(pop_model))

    art_neighbor_pred, preds_df = predict_neighbors(pop_model, src, req.limit)
    front_art_neighbor_pred = copy.deepcopy(art_neighbor_pred)

    # Convert dst IDs to MBIDs for frontend
    for i, _ in enumerate(front_art_neighbor_pred):
        front_art_neighbor_pred[i]['dst_artist_id'] = str(
            get_mbid_from_id(int(art_neighbor_pred[i]['dst_artist_id']))
        )

    # Build context embeddings for CVAE
    art_neighbor_pred_list = [(src_int, int(p['dst_artist_id'])) for p in art_neighbor_pred]
    preds_w_context = build_link_prediction_embeddings_from_artist_list(
        artist_list=art_neighbor_pred_list
    )
    preds_w_context['prob'] = [p['probability'] for p in art_neighbor_pred]

    # Generate synthetic tracks for each neighbor
    print("[artist-neighbors] Generating synthetic tracks for each neighbor (fallback)...")
    for i, (src_id, dst_id) in enumerate(zip(preds_w_context.src, preds_w_context.dst)):
        src_id, dst_id = int(src_id), int(dst_id)

        existing_tracks = check_existing_synthetic_tracks(src=src_id, dst=dst_id, limit=req.limit)
        track_ids = [track_id for track_id, _ in existing_tracks]

        if len(track_ids) == 0:
            print(f"[artist-neighbors] No existing tracks for {src_id} -> {dst_id}, generating...")
            track_ids = generate_synthetic_tracks(
                cvae_version=req.model_version,
                df_pred_links=preds_w_context.loc[preds_w_context.dst == dst_id],
                limit=req.limit,
            )

        front_art_neighbor_pred[i]['probability'] = float(
            preds_w_context.loc[preds_w_context.dst == dst_id, 'prob'].iloc[0]
        )
        front_art_neighbor_pred[i]['tracks'] = [int(tid) for tid in track_ids]

    return ArtistNeighborResponse(
        src_artist_id=req.src_artist_id,
        neighbors=[ArtistNeighborPrediction(**p) for p in front_art_neighbor_pred],
        model_version=req.model_version,
        latency_ms=(time.time() - start) * 1000,
    )
    
def get_artists_from_tracks(track_ids: List[int]):
    """Given a list of synthetic track IDs, fetch the corresponding src and dst artist IDs from the database."""
    conn = get_pg_conn()
    q = """
        SELECT 
            TRIM(SPLIT_PART(ac.name, ',', 1)) AS name1,
            COALESCE(NULLIF(TRIM(SPLIT_PART(ac.name, ',', 2)), ''), '') AS name2
        FROM l_artist_recording lar 
        JOIN recording r 
            ON lar.entity1 = r.id
        JOIN artist_credit ac
            ON r.artist_credit = ac.id
        WHERE lar.entity1 = ANY(%s::int[]);
    """
    df = pd.read_sql_query(q, conn, params=(track_ids,))
    conn.close()
    return df
    
@app.post("/ml/synthetic-tracks-similarity", response_model=TrackSimilarityResponse)
def synthetic_tracks_similarity_endpoint(req: SyntheticTrackSimilarityRequest):
    """Create a track similarity endpoint taking in src,dst,synthetic track id and returning the similarity of that track to the existing tracks between the src-dst pair."""

    """
    Returns: 
    LIST OF ->
        [class TrackResponse(BaseModel):
            id: str
            name: str
            popularity: Optional[float] = None
            synthetic: bool = False]
    """
    # Input should be list of tuples of (src,dst,track_id)
    
    print("DEBUG: Received request for synthetic track similarity with the following parameters:", req)
    t = TrackSimilarity(req)
    track_ids = []
    scores = []
    output = []
    for _, list_of_nbr_and_scores in t.sorted_genre_scores.items(): # {synth_tid: [(neighbor_tid,score), ...]}
        i = 0 # For each synthetic track we will return the top k most similar existing tracks, where k is req.num_similar_tracks
        for track_id, score in list_of_nbr_and_scores: # [(tid,score), ...]
            track_ids.append(track_id)
            scores.append(score)
            i += 1
            if i >= req.num_similar_tracks:
                break
    artists = get_artists_from_tracks(track_ids)
    for j,track_id in enumerate(track_ids):
        try: 
            tname = get_recording_name_from_id(track_id)
        except Exception as e:
            print(f"[ERROR] Failed to get track name for track_id {track_id}: {type(e).__name__}: {e}")
            tname = "Unknown Track Name"
                
        out = SimilarTrack(
            recording_name = tname, # This is a placeholder, we can adjust the query to get the recording name instead of artist name
            artist_name = artists.name1.iloc[j],
            artist_name_2 = artists.name2.iloc[j],
            similarity = scores[j]    
            )
        output.append(out)
    print("Type of output:", type(output))
    return TrackSimilarityResponse(similar_tracks=output)
    
    
@app.post("/interlude/daily-prediction", response_model=DailyPredictionResponse)
def daily_prediction_endpoint(req: DailyPredictionRequest):
    """Select a random artist matching the requested genre tag and return
    ML-predicted synthetic connections (table2 data) for that artist.

    Uses MusicBrainz artist_tag + tag tables to find genre-tagged artists,
    then delegates to the existing predict_neighbors pipeline.
    """
    import random as _random
    start = time.time()
    print("DEBUG: Received daily prediction request with parameters:", req)

    genre = req.genre.strip().lower()
    limit = req.limit

    # 1. Query artists tagged with the requested genre from MusicBrainz
    # Instead of querying from MusicBrainz we will 
    conn = get_pg_conn()
    genre_query = """
        SELECT a.id as artist_id, a.gid AS artist_mbid, a.name AS artist_name
        FROM artist a
        RIGHT JOIN spotify_genres sf 
            ON sf.artist_mbid = a.gid
        WHERE LOWER(sf.genre) = %s
            AND a.id IN (SELECT DISTINCT artist_id FROM artist_collab)
        LIMIT 200;
        """
    print("DEBUG: Executing genre query to find artists with genre tag:", genre)
    print("DEBUG: Genre query:", genre_query)
    artists_df = pd.read_sql_query(genre_query, conn, params=(genre,))
    conn.close()

    if artists_df.empty:
        raise HTTPException(status_code=404, detail=f"No artists found for genre '{genre}'")

    # 2. Pick a random seed artist
    seed_row = artists_df.sample(1, random_state=_random.randint(0, 999999)).iloc[0]
    src_artist_id = int(seed_row['artist_id'])
    src_artist_mbid = str(seed_row['artist_mbid'])
    src_artist_name = str(seed_row['artist_name'])

    print(f"[daily-prediction] Genre='{genre}', Seed artist: {src_artist_name} (id={src_artist_id}, mbid={src_artist_mbid})")

    # 3. Check for pre-computed connections (fast path)
    pred_connections = get_prediction_connections_for_src(src_artist_id, limit=limit)
    print(f"[daily-prediction] Found {len(pred_connections)} pre-computed connections")

    neighbors = []

    if len(pred_connections) >= limit:
        # Fast path: use cached predictions
        for _, row in pred_connections.iterrows():
            dst_int = int(row['dst'])
            prob = float(row['prob'])

            existing_tracks = check_existing_synthetic_tracks(src=src_artist_id, dst=dst_int, limit=5)
            track_ids = [track_id for track_id, _ in existing_tracks]

            if len(track_ids) == 0:
                pair_list = [(src_artist_id, dst_int)]
                preds_w_context = build_link_prediction_embeddings_from_artist_list(artist_list=pair_list)
                preds_w_context['prob'] = prob
                track_ids = generate_synthetic_tracks(
                    cvae_version=LOGIT_MODEL_VERSION,
                    df_pred_links=preds_w_context,
                    limit=5,
                )

            dst_mbid = str(get_mbid_from_id(dst_int))
            neighbors.append(ArtistNeighborPrediction(
                dst_artist_id=dst_mbid,
                probability=prob,
                tracks=[int(tid) for tid in track_ids],
            ))
    else:
        # Slow path: run ML pipeline
        logit_path = os.path.join(MODEL_ENGINEERING_DIR, f'logit_model_{LOGIT_MODEL_VERSION}.joblib')
        pop_model = load_logit_model(f"logit_model_{LOGIT_MODEL_VERSION}", logit_path)

        art_neighbor_pred, preds_df = predict_neighbors(pop_model, src_artist_id, limit)

        # Build context embeddings for CVAE
        art_neighbor_pred_list = [(src_artist_id, int(p['dst_artist_id'])) for p in art_neighbor_pred]
        preds_w_context = build_link_prediction_embeddings_from_artist_list(artist_list=art_neighbor_pred_list)
        preds_w_context['prob'] = [p['probability'] for p in art_neighbor_pred]

        for i, (src_id, dst_id) in enumerate(zip(preds_w_context.src, preds_w_context.dst)):
            src_id, dst_id = int(src_id), int(dst_id)

            existing_tracks = check_existing_synthetic_tracks(src=src_id, dst=dst_id, limit=5)
            track_ids = [track_id for track_id, _ in existing_tracks]

            if len(track_ids) == 0:
                track_ids = generate_synthetic_tracks(
                    cvae_version=LOGIT_MODEL_VERSION,
                    df_pred_links=preds_w_context.loc[preds_w_context.dst == dst_id],
                    limit=5,
                )

            dst_mbid = str(get_mbid_from_id(dst_id))
            neighbors.append(ArtistNeighborPrediction(
                dst_artist_id=dst_mbid,
                probability=float(art_neighbor_pred[i]['probability']),
                tracks=[int(tid) for tid in track_ids],
            ))

    return DailyPredictionResponse(
        date=req.date,
        genre=genre,
        src_artist_id=src_artist_mbid,
        src_artist_name=src_artist_name,
        neighbors=neighbors,
        model_version=LOGIT_MODEL_VERSION,
        latency_ms=(time.time() - start) * 1000,
    )


@app.post("/ml/generate/tracks", response_model=SyntheticTrackResponse)
def generate_tracks_endpoint(req: SyntheticTrackRequest):
    start = time.time()

    # src_emb = get_artist_embeddings(req.src_artist_id)
    # dst_emb = get_artist_embeddings(req.dst_artist_id)

    if not req.src_artist_id or not req.dst_artist_id:
        raise HTTPException(status_code=404, detail="Missing artist embeddings")


    logit_path = os.path.join(MODEL_ENGINEERING_DIR,'logit_model_v1.joblib')
    logit_model = load_logit_model("logit_v1",logit_path)
    probability = predict_artist_link(logit_model, req.src_artist_id, req.dst_artist_id)

    cvae_version = load_cvae_model(req.model_version)
    pop_model = load_popularity_model()

    tracks = generate_synthetic_tracks(
        cvae_version,
        pop_model,
        req.src_artist_id,
        req.dst_artist_id,
        req.limit
    )

    return SyntheticTrackResponse(
        src_artist_id=req.src_artist_id,
        dst_artist_id=req.dst_artist_id,
        probability=probability,
        tracks=[SyntheticTrack(**t) for t in tracks],
        model_version=req.model_version,
        latency_ms=(time.time() - start) * 1000
    )

