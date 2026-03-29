"""
MBID → Spotify Artist ID Mapping Pipeline

Produces a mapping table: artist_mbid (UUID) → spotify_artist_id (string)

Strategy:
  1. MB Link   – Use Spotify URLs already stored in MusicBrainz (high confidence)
  2. Name search – Fall back to Spotify artist search API with Levenshtein matching

Artists are sourced from lastfm_artist_stats ordered by popularity DESC.
"""

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

from config.config import DB_URL

# ---------- CONFIG ----------
DB_DSN = DB_URL

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
    
    sql = """
    CREATE TABLE IF NOT EXISTS spotify_genres (
        spotify_artist_id TEXT PRIMARY KEY,
        genre TEXT,
        fetched_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
    );
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    print("[MIGRATE] spotify_genres table ready")


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
    """Search Spotify for artists matching a name. Returns list of artist dicts."""
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


# ============================================================
# Fetch artists to process
# ============================================================

def fetch_artists(conn):
    """Get all artists from lastfm_artist_stats ordered by popularity DESC.

    Returns list of (artist_mbid, artist_name).
    """
    sql = """
        SELECT las.artist_mbid, las.artist_name
        FROM lastfm_artist_stats las
        LEFT JOIN artist_mbid_spotify ams ON ams.artist_mbid = las.artist_mbid
        WHERE ams.artist_mbid IS NULL
        ORDER BY las.popularity_score DESC;
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


# ============================================================
# Bulk-load MB → Spotify links from MusicBrainz DB
# ============================================================

def fetch_mb_spotify_links(conn):
    """Query MusicBrainz for all artist → Spotify URL links.

    Returns dict: artist_mbid (str) → spotify_artist_id (str).
    """
    sql = """
        SELECT a.gid::text AS artist_mbid,
               u.url
        FROM musicbrainz.l_artist_url lau
        JOIN musicbrainz.artist a ON a.id = lau.entity0
        JOIN musicbrainz.url u ON u.id = lau.entity1
        WHERE u.url LIKE '%%open.spotify.com/artist/%%';
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    mapping = {}
    for mbid, url in rows:
        m = RE_SPOTIFY_ID.search(url)
        if m:
            mapping[mbid] = m.group(1)

    print(f"[MB LINKS] Loaded {len(mapping)} MusicBrainz → Spotify links")
    return mapping


# ============================================================
# Mapping logic for a single artist
# ============================================================

def map_single_artist(mbid_str, mb_name, mb_links, token):
    """Map a single MBID to a Spotify artist ID.

    Returns (spotify_id, score, ambiguous, source, genres) or None on failure.
    """

    # # ---- 1. MB Link (deterministic, high confidence) ----
    # if mbid_str in mb_links:
    #     spotify_id = mb_links[mbid_str]
    #     try:
    #         artist_data = spotify_get_artist(spotify_id, token)
    #         if artist_data:
    #             spotify_name = artist_data.get("name", "")
    #             score = name_similarity(spotify_name, mb_name)
    #             ambiguous = score < SIMILARITY_THRESHOLD
    #             return spotify_id, score, ambiguous, "mb_link"
    #         else:
    #             # Spotify ID from MB exists but artist not found on Spotify
    #             # (e.g. deleted profile) — fall through to name search
    #             pass
    #     except Exception:
    #         pass

    # ---- 2. Spotify Name Search (fallback) ----
    try:
        time.sleep(SLEEP_BETWEEN_REQUESTS)
        results = spotify_search_artist(mb_name, token)

        best_match = None
        best_score = 0.0
        for r in results:
            score = name_similarity(r.get("name", ""), mb_name)
            genres = r.get("genres", [])
            if score > best_score:
                best_score = score
                best_match = r

        if best_match and best_score >= SIMILARITY_THRESHOLD:
            # If multiple candidates exceed threshold, pick highest popularity
            tied = [
                r for r in results
                if name_similarity(r.get("name", ""), mb_name) >= SIMILARITY_THRESHOLD
            ]
            if len(tied) > 1:
                tied.sort(key=lambda r: r.get("popularity", 0), reverse=True)
                best_match = tied[0]
                best_score = name_similarity(best_match.get("name", ""), mb_name)

            return best_match["id"], best_score, False, "spotify_name", genres

        # Below threshold — still record as ambiguous if there's a candidate
        if best_match:
            return best_match["id"], best_score, True, "spotify_name"

        return None, 0.0, True, "not_found"

    except Exception:
        return None, 0.0, True, "error"


# ============================================================
# Batch upsert
# ============================================================

def upsert_mappings(conn, rows, genres):
    sql = """
        INSERT INTO artist_mbid_spotify
        (artist_mbid, spotify_artist_id, source, ambiguous, similarity_score, fetched_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (artist_mbid) DO UPDATE SET
          spotify_artist_id = EXCLUDED.spotify_artist_id,
          source = EXCLUDED.source,
          ambiguous = EXCLUDED.ambiguous,
          similarity_score = EXCLUDED.similarity_score,
          fetched_at = NOW();
    """
    with conn.cursor() as cur:
        execute_batch(cur, sql, rows, page_size=100)
    conn.commit()

    sql = """
        INSERT INTO spotify_genres (spotify_artist_id, genre, fetched_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (spotify_artist_id) DO UPDATE SET
          genre = EXCLUDED.genre,
          fetched_at = NOW();
    """
    genre_rows = []
    for spotify_id, genre_list in zip(rows, genres):
        if spotify_id[1] and genre_list:  # spotify_artist_id is at index 1
            for genre in genre_list:
                genre_rows.append((spotify_id[1], genre))
                
    with conn.cursor() as cur:
        execute_batch(cur, sql, genre_rows, page_size=100)
    conn.commit()
    

# ============================================================
# Main pipeline
# ============================================================

def main():
    conn = psycopg2.connect(DB_DSN)
    migrate(conn)

    # Pre-load all MB → Spotify links
    # mb_links = fetch_mb_spotify_links(conn)

    # Fetch artists to process (skips already-mapped ones)
    artists = fetch_artists(conn)
    print(f"[PIPELINE] Processing {len(artists)} artists\n")

    if not artists:
        print("Nothing to process — all artists already mapped.")
        conn.close()
        return

    token = get_spotify_token()

    buffer = []
    buffer2 = [] # Buffer for the genres
    searched = found = inserted = 0
    reasons = {
        "mb_link": 0,
        "spotify_name": 0,
        "not_found": 0,
        "error": 0,
        "genres_skipped": 0,
    }

    def process_artist(args):
        mbid, name = args
        mbid_str = str(mbid)
        # Refresh token if needed
        t = get_spotify_token()
        return map_single_artist(mbid_str, name, {}, t,)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_artist, (mbid, name)): (mbid, name)
            for mbid, name in artists
        }

        for i, future in enumerate(
            tqdm(as_completed(futures), total=len(futures)), start=1
        ):
            searched += 1

            try:
                result = future.result()
                if result is None:
                    reasons["error"] += 1
                    continue

                spotify_id, score, ambiguous, source, genres = result
                if len(genres) == 0:
                    reasons["genres_skipped"] += 1
                reasons[source] = reasons.get(source, 0) + 1

                mbid, name = futures[future]

                if spotify_id:
                    found += 1
                    buffer.append((
                        str(mbid),
                        spotify_id,
                        source,
                        ambiguous,
                        round(score, 4),
                    ))
                    buffer2.append(genres)
                else:
                    # Record not_found entries too so we skip them next run
                    buffer.append((
                        str(mbid),
                        None,
                        source,
                        True,
                        0.0,
                    ))
                    buffer2.append(genres) 

                if len(buffer) >= UPSERT_BATCH_SIZE:
                    upsert_mappings(conn, buffer,buffer2)
                    inserted += len(buffer)
                    buffer.clear()
                    buffer2.clear()
                    print(
                        f"[DB WRITE] inserted={inserted} "
                        f"found={found} searched={searched}"
                    )

            except Exception as e:
                print(f"[FUTURE ERROR] {e}")

            if i % PROGRESS_EVERY == 0:
                print(
                    f"[PROGRESS] searched={searched} found={found} "
                    f"inserted={inserted} buffer={len(buffer)}"
                )
                for k, v in reasons.items():
                    print(f"  {k}: {v}")

    # Flush remaining buffer
    if buffer:
        upsert_mappings(conn, buffer, buffer2)
        inserted += len(buffer)

    print("\n==== FINAL SUMMARY ====")
    print(f"Searched: {searched}")
    print(f"Found:    {found}")
    print(f"Inserted: {inserted}")
    for k, v in reasons.items():
        print(f"  {k:15s}: {v}")
    print("=======================\n")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
