"""
1. Automatic Artist Selector by genre
   - This creates a playlist for us given the artist
   Spotify Genre:
      - spotify Search q = genre:pop, type = artist, limit =10 offset = j Loop 100 times
      - Get 1000 Artists, maybe we can random offset (jitter)
      - This will give us 1000 artists
      - Do that for each unique genre
      - genreArtistLookup[genre] = [artist1,artist2,...]
      - Once we select for each genre, input them into the model and create the playlist
      - Create the playlist 
      - Display it, and send to every user that is signed up
"""

"""
MBID → Spotify Artist ID Mapping Pipeline

Produces a mapping table: artist_mbid (UUID) → spotify_artist_id (string)

Strategy:
  1. MB Link   – Use Spotify URLs already stored in MusicBrainz (high confidence)
  2. Name search – Fall back to Spotify artist search API with Levenshtein matching

Artists are sourced from lastfm_artist_stats ordered by popularity DESC.
"""

from typing import List


with open("/home/jonnym/Desktop/MelodyMap/internal/interlude_service/spotify/genres.txt") as f:
    GENRES = [line.strip() for line in f.readlines()]
    
def add_genres(genres: List[str] | str):
    # Add in genres to the txt file if not in there
    if isinstance(genres, str):
        genres = [genres]
    for genre in genres:
        if genre not in GENRES:
            with open("/home/jonnym/Desktop/MelodyMap/internal/interlude_service/spotify/genres.txt", "a") as f:
                f.write(genre + "\n")
            GENRES.append(genre)

import base64
import os
import re
import time
import requests
import psycopg2
from psycopg2.extras import execute_batch
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

try:
    from Levenshtein import distance as lev_distance
except ImportError:
    from rapidfuzz.distance import Levenshtein
    lev_distance = Levenshtein.distance


# ---------- CONFIG ----------
DB_DSN = os.getenv("DB_DSN", "postgresql://localhost:5432/music_data")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "9ce2d15fb4114cceb56097c7fa53e734")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "6a94edbec2cf45a290b4f3d53762c403")

SIMILARITY_THRESHOLD = 0.8
MAX_WORKERS = 5
UPSERT_BATCH_SIZE = 1000
PROGRESS_EVERY = 5000
SLEEP_BETWEEN_REQUESTS = 0.1  # seconds between Spotify API calls
# ----------------------------

# Regex to extract Spotify artist ID from URL
RE_SPOTIFY_ID = re.compile(r"open\.spotify\.com/artist/([a-zA-Z0-9]+)")


# ============================================================
# Table creation
# ============================================================

def migrate(conn):
    sql = """
    CREATE TABLE IF NOT EXISTS artist_mbid_spotify (
        artist_mbid UUID PRIMARY KEY,
        spotify_artist_id TEXT,
        source TEXT DEFAULT 'mb_link',
        ambiguous BOOLEAN DEFAULT FALSE,
        similarity_score FLOAT,
        fetched_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_artist_mbid_spotify_source
        ON artist_mbid_spotify(source);
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    print("[MIGRATE] artist_mbid_spotify table ready")


# ============================================================
# Name similarity
# ============================================================

def name_similarity(name1: str, name2: str) -> float:
    n1 = name1.lower().strip()
    n2 = name2.lower().strip()
    if not n1 or not n2:
        return 0.0
    max_len = max(len(n1), len(n2))
    return 1 - lev_distance(n1, n2) / max_len


# ============================================================
# Spotify Client Credentials token
# ============================================================

_spotify_token = None
_spotify_token_expiry = 0


def get_spotify_token() -> str:
    """Obtain a Spotify access token via Client Credentials flow."""
    global _spotify_token, _spotify_token_expiry

    if _spotify_token and time.time() < _spotify_token_expiry - 60:
        return _spotify_token

    creds = base64.b64encode(
        f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()
    ).decode()

    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        headers={"Authorization": f"Basic {creds}"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    _spotify_token = data["access_token"]
    _spotify_token_expiry = time.time() + data.get("expires_in", 3600)
    print(f"[SPOTIFY] Obtained access token (expires in {data.get('expires_in', '?')}s)")
    return _spotify_token


# ============================================================
# Spotify API helpers
# ============================================================

def spotify_get_artist(spotify_id: str, token: str):
    """Fetch a single artist by Spotify ID. Returns dict or None."""
    resp = requests.get(
        f"https://api.spotify.com/v1/artists/{spotify_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 2))
        time.sleep(retry_after)
        return spotify_get_artist(spotify_id, token)
    if resp.status_code != 200:
        return None
    return resp.json()


def spotify_search_artist(query: str, token: str, limit: int = 5):
    """Search Spotify for artists matching a name. Returns list of artist dicts.
    Inputs: query = "genre:pop", token = "BQD...", limit = 5
        Output: [
            {
                "id": "1Xyo4u8uXC1ZmMpatF05PJ",
                "name": "The Weeknd",
                "genres": ["canadian contemporary r&b", "canadian pop", ...],
                ...
            },
            ...
        ]
    """
    resp = requests.get(
        "https://api.spotify.com/v1/search",
        params={"q": query, "type": "artist", "limit": str(limit)},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 2))
        time.sleep(retry_after)
        return spotify_search_artist(query, token, limit)
    if resp.status_code != 200:
        return []
    data = resp.json()
    return data.get("artists", {}).get("items", [])

