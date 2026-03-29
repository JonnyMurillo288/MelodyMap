import json
import math
import time
import requests
import psycopg2
from psycopg2.extras import execute_batch
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from config.config import DB_URL, LAST_FM_ARTITST_TABLE

LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"

# ---------- CONFIG ----------
DB_DSN = DB_URL
API_KEY_PATH = "../config/last_fm_keys.json"

MAX_WORKERS = 5          # keep conservative to avoid rate limits
UPSERT_BATCH_SIZE = 20000
PROGRESS_EVERY = 10000
# ----------------------------


def load_api_key(path: str) -> str:
    with open(path, "r") as f:
        return json.load(f)["api_key"]


def migrate(conn):
    sql = """
    CREATE TABLE IF NOT EXISTS lastfm_artist_stats (
        artist_mbid UUID PRIMARY KEY,
        artist_name TEXT,
        listeners BIGINT,
        playcount BIGINT,
        popularity_score DOUBLE PRECISION,
        fetched_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
    );
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def fetch_artists(conn, limit=None):
    sql = """
        WITH ac AS (
            SELECT DISTINCT artist_id
            FROM artist_collab
        )
        SELECT a.gid, a.name
        FROM ac
        JOIN artist a ON ac.artist_id = a.id
        OFFSET 132763;
    """
    if limit:
        sql += f" LIMIT {limit}"

    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def parse_stats(mbid, artist):
    stats = artist.get("stats")
    if not stats:
        return None

    listeners = int(stats.get("listeners", 0))
    playcount = int(stats.get("playcount", 0))

    popularity = (
        math.log10(listeners + 1) * 0.6 +
        math.log10(playcount + 1) * 0.4
    )

    return (
        mbid,
        artist.get("name"),
        listeners,
        playcount,
        round(popularity, 4),
    )


def get_lastfm_stats(mbid, artist_name, api_key):
    base = {
        "method": "artist.getinfo",
        "api_key": api_key,
        "format": "json",
    }

    # ---- 1. MBID lookup ----
    try:
        r = requests.get(
            LASTFM_URL,
            params={**base, "mbid": str(mbid)},
            timeout=10,
        )

        if r.status_code != 200:
            return None, "http_fail"

        data = r.json()

        if "error" in data:
            if data["error"] == 29:
                return None, "rate_limited"
            if data["error"] == 6:
                pass  # fallback to name
            else:
                return None, "mbid_not_found"
        else:
            artist = data.get("artist")
            if artist and "stats" in artist:
                return parse_stats(mbid, artist), "ok_mbid"

    except requests.exceptions.RequestException:
        return None, "request_fail"
    except Exception:
        return None, "parse_fail"

    # ---- 2. Name fallback ----
    try:
        r = requests.get(
            LASTFM_URL,
            params={**base, "artist": artist_name, "autocorrect": 1},
            timeout=10,
        )

        if r.status_code != 200:
            return None, "http_fail"

        data = r.json()

        if "error" in data:
            if data["error"] == 29:
                return None, "rate_limited"
            return None, "name_not_found"

        artist = data.get("artist")
        if artist and "stats" in artist:
            return parse_stats(mbid, artist), "ok_name"

        return None, "name_not_found"

    except requests.exceptions.RequestException:
        return None, "request_fail"
    except Exception:
        return None, "parse_fail"


def upsert_stats(conn, rows):
    sql = """
        INSERT INTO lastfm_artist_stats
        (artist_mbid, artist_name, listeners, playcount, popularity_score, fetched_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (artist_mbid) DO UPDATE SET
          artist_name = EXCLUDED.artist_name,
          listeners = EXCLUDED.listeners,
          playcount = EXCLUDED.playcount,
          popularity_score = EXCLUDED.popularity_score,
          fetched_at = NOW();
    """
    with conn.cursor() as cur:
        execute_batch(cur, sql, rows, page_size=100)
    conn.commit()


def main():
    api_key = load_api_key(API_KEY_PATH)
    conn = psycopg2.connect(DB_DSN)

    migrate(conn)

    # LIMIT TEMPORARILY when debugging large runs
    artists = fetch_artists(conn, limit=None)
    print(f"Processing {len(artists)} artists\n")

    buffer = []

    # ---- Counters ----
    searched = found = inserted = 0
    reasons = {
        "ok_mbid": 0,
        "ok_name": 0,
        "mbid_not_found": 0,
        "name_not_found": 0,
        "rate_limited": 0,
        "http_fail": 0,
        "request_fail": 0,
        "parse_fail": 0,
    }

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(get_lastfm_stats, mbid, name, api_key): (mbid, name)
            for mbid, name in artists
        }

        for i, future in enumerate(
            tqdm(as_completed(futures), total=len(futures)), start=1
        ):
            searched += 1

            try:
                result, reason = future.result()
                reasons[reason] += 1

                if result:
                    found += 1
                    buffer.append(result)

                if len(buffer) >= UPSERT_BATCH_SIZE:
                    upsert_stats(conn, buffer)
                    inserted += len(buffer)
                    buffer.clear()

                    print(
                        f"[DB WRITE] inserted={inserted} "
                        f"found={found} searched={searched}"
                    )

            except Exception as e:
                print("[FUTURE ERROR]", e)

            if i % PROGRESS_EVERY == 0:
                print(
                    f"[PROGRESS] searched={searched} found={found} inserted={inserted} "
                    f"buffer={len(buffer)} rate_limited={reasons['rate_limited']}"
                )

                # crude backoff if rate-limited
                if reasons["rate_limited"] > 0:
                    print("[BACKOFF] sleeping 10s due to rate limit")
                    time.sleep(10)

    if buffer:
        upsert_stats(conn, buffer)
        inserted += len(buffer)

    print("\n==== FINAL SUMMARY ====")
    print(f"Searched: {searched}")
    print(f"Found:    {found}")
    print(f"Inserted: {inserted}")
    for k, v in reasons.items():
        print(f"{k:15s}: {v}")
    print("=======================\n")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
