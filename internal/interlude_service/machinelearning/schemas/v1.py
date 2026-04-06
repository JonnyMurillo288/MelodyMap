"""
Pydantic v2 request/response schemas for the /api/v1/ endpoints.
These are the standardized schemas for the public API.
"""
from pydantic import BaseModel, Field
from typing import Optional, Any


# ---------------------------------------------------------------
# Shared response envelope
# ---------------------------------------------------------------
class ResponseMeta(BaseModel):
    model_version: str = ""
    latency_ms: float = 0.0
    cached: bool = False
    request_id: str = ""


class APIResponse(BaseModel):
    """Standard response wrapper. All v1 endpoints return this shape."""
    data: Any
    meta: ResponseMeta = ResponseMeta()


class APIError(BaseModel):
    code: str
    message: str
    request_id: str = ""


class ErrorResponse(BaseModel):
    error: APIError


# ---------------------------------------------------------------
# Prediction Endpoints
# ---------------------------------------------------------------
class ConnectionRequest(BaseModel):
    src_artist: str = Field(..., description="MBID, Spotify ID, or artist name")
    dst_artist: str = Field(..., description="MBID, Spotify ID, or artist name")
    model_version: Optional[str] = Field(None, description="Logit model version (e.g. 'v5'). None = default.")
    limit: int = Field(default=5, le=25, description="Number of synthetic tracks to generate")


class ConnectionData(BaseModel):
    src_artist: str
    dst_artist: str
    src_name: str = ""
    dst_name: str = ""
    probability: float
    connection_potential: int = 0  # 0-100 intuitive score for UX display
    tracks: list = []
    features_used: dict = {}


class NeighborRequest(BaseModel):
    artist: str = Field(..., description="MBID, Spotify ID, or artist name")
    limit: int = Field(default=20, le=100)
    min_probability: Optional[float] = Field(None, ge=0.0, le=1.0)
    genre_filter: Optional[list[str]] = None
    model_version: Optional[str] = None


class NeighborItem(BaseModel):
    artist_id: str
    name: str = ""
    probability: float
    tracks: list = []


class NeighborsData(BaseModel):
    artist: str
    artist_name: str = ""
    neighbors: list[NeighborItem]


class BatchPair(BaseModel):
    src: str
    dst: str


class BatchRequest(BaseModel):
    pairs: list[BatchPair] = Field(..., max_length=1000)
    model_version: Optional[str] = None


class BatchResultItem(BaseModel):
    src: str
    dst: str
    probability: float


class BatchData(BaseModel):
    results: list[BatchResultItem]


# ---------------------------------------------------------------
# Compare / A-B Test (Strategy 4.2)
# ---------------------------------------------------------------
class CompareRequest(BaseModel):
    src_artist: str
    dst_artist: str
    versions: list[str] = Field(..., min_length=2, max_length=5, description="Model versions to compare")


class CompareResultItem(BaseModel):
    version: str
    probability: float
    latency_ms: float


class CompareData(BaseModel):
    src_artist: str
    dst_artist: str
    results: list[CompareResultItem]


# ---------------------------------------------------------------
# Generation Endpoints
# ---------------------------------------------------------------
class TrackGenRequest(BaseModel):
    src_artist: str
    dst_artist: str
    num_tracks: int = Field(default=5, le=20)
    model_version: Optional[str] = None  # CVAE version


class SyntheticTrackItem(BaseModel):
    track_id: int
    features: dict = {}


class TrackGenData(BaseModel):
    src_artist: str
    dst_artist: str
    probability: float = 0.0
    tracks: list[SyntheticTrackItem]


class PlaylistRequest(BaseModel):
    synthetic_track_ids: list[int]
    num_similar: int = Field(default=5, le=25)


class SimilarTrackItem(BaseModel):
    recording_name: str
    artist_name: str
    artist_name_2: str = ""
    similarity: float


class PlaylistData(BaseModel):
    similar_tracks: list[SimilarTrackItem]


# ---------------------------------------------------------------
# Artist Profile
# ---------------------------------------------------------------
class ArtistProfileData(BaseModel):
    name: str
    artist_id: int
    mbid: str
    spotify_id: Optional[str] = None
    popularity: Optional[float] = None
    genre_distribution: dict = {}
    collab_count: int = 0
    top_collabs: list[dict] = []
    embedding_available: bool = False


# ---------------------------------------------------------------
# Auth
# ---------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    org_name: Optional[str] = None


class RegisterResponse(BaseModel):
    api_key: str
    tier: str
    rate_limit_per_hour: int
    message: str = "Save this API key securely. It will not be shown again."


# ---------------------------------------------------------------
# Model Info
# ---------------------------------------------------------------
class ModelInfoData(BaseModel):
    logit: dict
    cvae: dict
    currently_loaded: list[str] = []


# ---------------------------------------------------------------
# Health
# ---------------------------------------------------------------
class HealthData(BaseModel):
    status: str = "healthy"
    models_loaded: list[str] = []
    db_connected: bool = False
    version: str = "1.0.0"


# ---------------------------------------------------------------
# Feedback (Strategy 4.2 - online learning prep)
# ---------------------------------------------------------------
class FeedbackRequest(BaseModel):
    prediction_src: str
    prediction_dst: str
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None


# ---------------------------------------------------------------
# What-If Scenarios (Phase 2)
# ---------------------------------------------------------------
class WhatIfScenario(BaseModel):
    genre_target: Optional[str] = None
    popularity_range: Optional[list[int]] = Field(None, min_length=2, max_length=2)
    mood_target: Optional[str] = None


class WhatIfRequest(BaseModel):
    artists: list[str] = Field(..., min_length=2, max_length=10, description="2-10 artist identifiers (MBID, Spotify ID, or name)")
    scenario: Optional[WhatIfScenario] = None
    model_version: Optional[str] = None
    num_tracks: int = Field(default=5, le=20)
    num_similar: int = Field(default=5, le=25)


class WhatIfPairResult(BaseModel):
    src_artist: str
    src_name: str = ""
    dst_artist: str
    dst_name: str = ""
    probability: float
    synthetic_tracks: list[dict] = []
    similar_real_tracks: list[dict] = []


class WhatIfData(BaseModel):
    scenarios: list[WhatIfPairResult]


# ---------------------------------------------------------------
# Daily Trends (Phase 2)
# ---------------------------------------------------------------
class FeaturedConnection(BaseModel):
    src_artist_name: str
    dst_artist_name: str
    src_artist_id: int
    dst_artist_id: int
    probability: float
    genre: str
    synthetic_track_ids: list[int] = []


class DailyTrendsData(BaseModel):
    date: str
    featured_connections: list[FeaturedConnection]


# ---------------------------------------------------------------
# Dataset Export (Phase 2)
# ---------------------------------------------------------------
class DatasetExportParams(BaseModel):
    format: str = Field(default="csv", pattern="^(csv|parquet)$")
    genre: Optional[str] = None
    min_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    max_probability: float = Field(default=1.0, ge=0.0, le=1.0)
    limit: int = Field(default=10000, ge=1)
    model_version: Optional[str] = None


# ---------------------------------------------------------------
# Stripe Tier Upgrade (Phase 2 - internal)
# ---------------------------------------------------------------
class UpgradeTierRequest(BaseModel):
    email: str
    tier: str = Field(..., pattern="^(free|researcher|enterprise)$")
