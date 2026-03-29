"""
Prometheus metrics for the Interlude ML service.

Covers all three metric categories from Strategy 4.3:
  - Model Quality: prediction distribution, genre diversity
  - System Health: latency, cache hits, errors, DB query timing
  - Business Metrics: API calls by tier, playlist creations, exports

Exposes /metrics endpoint via prometheus_client ASGI app.
"""
import time
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


# ---------------------------------------------------------------
# System Health (Strategy 4.3)
# ---------------------------------------------------------------
REQUEST_LATENCY = Histogram(
    "interlude_request_latency_seconds",
    "Request latency by endpoint and status",
    ["endpoint", "method", "status"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

CACHE_HITS = Counter(
    "interlude_cache_hits_total",
    "Prediction cache hits vs misses",
    ["cache_type", "hit"],  # cache_type: prediction, embedding, profile; hit: true/false
)

REQUEST_ERRORS = Counter(
    "interlude_request_errors_total",
    "Errors by endpoint and type",
    ["endpoint", "error_type"],  # validation, not_found, model_error, rate_limit
)

DB_QUERY_DURATION = Histogram(
    "interlude_db_query_seconds",
    "Database query duration",
    ["query_name"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.5, 1.0],
)

REQUESTS_IN_PROGRESS = Gauge(
    "interlude_requests_in_progress",
    "Number of requests currently being processed",
    ["endpoint"],
)

# ---------------------------------------------------------------
# Model Quality (Strategy 4.3)
# ---------------------------------------------------------------
PREDICTION_DISTRIBUTION = Histogram(
    "interlude_prediction_probability",
    "Distribution of prediction probabilities output by the model",
    ["model_version"],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

GENRE_DIVERSITY = Gauge(
    "interlude_prediction_genre_diversity",
    "Genre diversity of recent predictions (unique genres in last batch)",
    ["model_version"],
)

# ---------------------------------------------------------------
# Business Metrics (Strategy 4.3)
# ---------------------------------------------------------------
API_CALLS_BY_TIER = Counter(
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
    "Dataset export requests",
    ["format"],  # csv, parquet
)

FEEDBACK_SUBMISSIONS = Counter(
    "interlude_feedback_submissions_total",
    "User feedback submissions on predictions",
)


# ---------------------------------------------------------------
# Middleware: auto-instrument request latency
# ---------------------------------------------------------------
class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip metrics endpoint itself
        if path == "/metrics":
            return await call_next(request)

        # Normalize path for cardinality control
        # e.g., /api/v1/artist/12345/profile -> /api/v1/artist/{id}/profile
        normalized = path
        parts = path.strip("/").split("/")
        if len(parts) >= 4 and parts[0] == "api" and parts[1] == "v1" and parts[2] == "artist":
            normalized = "/api/v1/artist/{id}/" + "/".join(parts[4:]) if len(parts) > 4 else "/api/v1/artist/{id}/profile"

        REQUESTS_IN_PROGRESS.labels(endpoint=normalized).inc()
        start = time.time()

        try:
            response = await call_next(request)
        except Exception:
            REQUEST_ERRORS.labels(endpoint=normalized, error_type="unhandled").inc()
            REQUESTS_IN_PROGRESS.labels(endpoint=normalized).dec()
            raise

        duration = time.time() - start
        status = str(response.status_code)

        REQUEST_LATENCY.labels(
            endpoint=normalized, method=request.method, status=status
        ).observe(duration)

        REQUESTS_IN_PROGRESS.labels(endpoint=normalized).dec()

        # Track errors
        if response.status_code >= 400:
            error_type = "client_error" if response.status_code < 500 else "server_error"
            REQUEST_ERRORS.labels(endpoint=normalized, error_type=error_type).inc()

        # Track by tier if user is authenticated
        user = getattr(request.state, "user", None)
        if user and isinstance(user, dict):
            tier = user.get("tier", "unknown")
            API_CALLS_BY_TIER.labels(tier=tier, endpoint=normalized).inc()

        return response


# ---------------------------------------------------------------
# Helpers for use in endpoint handlers
# ---------------------------------------------------------------
def observe_prediction(probability: float, model_version: str):
    """Record a prediction probability for distribution tracking."""
    PREDICTION_DISTRIBUTION.labels(model_version=model_version).observe(probability)


def observe_cache(cache_type: str, hit: bool):
    """Record a cache hit or miss."""
    CACHE_HITS.labels(cache_type=cache_type, hit=str(hit).lower()).inc()


def observe_db_query(query_name: str, duration_seconds: float):
    """Record database query duration."""
    DB_QUERY_DURATION.labels(query_name=query_name).observe(duration_seconds)


def track_genre_diversity(genre_count: int, model_version: str):
    """Update genre diversity gauge."""
    GENRE_DIVERSITY.labels(model_version=model_version).set(genre_count)


# ---------------------------------------------------------------
# /metrics endpoint handler
# ---------------------------------------------------------------
async def metrics_endpoint(request: Request):
    """Prometheus metrics scrape endpoint."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
