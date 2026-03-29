"""This file contains the logic for fetching the time period that an artist was active from the last.fm API, 
and storing them in the database."""

import json
import math
import time
import requests
import psycopg2
import re
from datetime import datetime
from psycopg2.extras import execute_batch
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
# from config.config import DB_URL

LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"

# ---------- CONFIG ----------
DB_DSN = "postgres://postgres:baseball162162@localhost:5432/musicbrainz_db?sslmode=disable"
API_KEY_PATH = "../config/last_fm_keys.json"

MAX_WORKERS = 5
UPSERT_BATCH_SIZE = 5000
PROGRESS_EVERY = 5000
TOP_ALBUM_LIMIT = 10  # keep small to avoid rate explosion
# ----------------------------


def load_api_key(path: str) -> str:
    with open(path, "r") as f:
        return json.load(f)["api_key"]


def migrate(conn):
    sql = """
    CREATE TABLE IF NOT EXISTS lastfm_artist_year (
        artist_mbid UUID PRIMARY KEY,
        artist_name TEXT,
        approx_debut_year INT,
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
        JOIN artist a ON ac.artist_id = a.id;
    """
    if limit:
        sql += f" LIMIT {limit}"

    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def extract_year(date_str):
    if not date_str:
        return None

    date_str = date_str.strip()

    try:
        return datetime.strptime(date_str, "%d %b %Y, %H:%M").year
    except:
        pass

    try:
        return datetime.strptime(date_str, "%d %b %Y").year
    except:
        pass

    match = re.search(r"\b(19|20)\d{2}\b", date_str)
    if match:
        return int(match.group())

    return None


def get_lastfm_year(mbid, artist_name, api_key):
    base = {
        "api_key": api_key,
        "format": "json",
    }

    def fetch_top_albums(params):
        r = requests.get(LASTFM_URL, params=params, timeout=10)

        if r.status_code != 200:
            return None, "http_fail"

        data = r.json()

        if "error" in data:
            if data["error"] == 29:
                return None, "rate_limited"
            if data["error"] == 6:
                return None, "not_found"
            return None, "api_error"

        albums = data.get("topalbums", {}).get("album", [])
        return albums[:TOP_ALBUM_LIMIT], "ok"

    def fetch_album_year(album_name):
        try:
            r = requests.get(
                LASTFM_URL,
                params={
                    **base,
                    "method": "album.getinfo",
                    "artist": artist_name,
                    "album": album_name,
                },
                timeout=10,
            )
            if r.status_code != 200:
                return None

            data = r.json()
            breakpoint()
            release = data.get("album", {}).get("releasedate")
            return extract_year(release)

        except:
            try:
                r = requests.get(
                    LASTFM_URL,
                    params={
                        **base,
                        "method": "album.search",
                        "artist": artist_name,
                        "album": album_name,
                    },
                    timeout=10,
                )
                if r.status_code != 200:
                    return None

                data = r.json()
                release = data.get("album", {}).get("wiki", {}).get("published")
                return extract_year(release)
            except:
                return None

    # ---- 1. MBID lookup ----
    try:
        albums, status = fetch_top_albums({
            **base,
            "method": "artist.getTopAlbums",
            "mbid": str(mbid),
        })

        if status == "rate_limited":
            return None, "rate_limited"

        if albums:
            years = []
            for album in albums:
                y = fetch_album_year(album.get("name"))
                if y:
                    years.append(y)

            if years:
                return (
                    str(mbid),
                    artist_name,
                    min(years),
                ), "ok_mbid"

    except requests.exceptions.RequestException:
        return None, "request_fail"
    except Exception:
        return None, "parse_fail"

    # ---- 2. Name fallback ----
    try:
        albums, status = fetch_top_albums({
            **base,
            "method": "artist.getTopAlbums",
            "artist": artist_name,
            "autocorrect": 1,
        })

        if status == "rate_limited":
            return None, "rate_limited"

        if not albums:
            return None, "name_not_found"

        years = []
        for album in albums:
            y = fetch_album_year(album.get("name"))
            if y:
                years.append(y)

        if years:
            return (
                str(mbid),
                artist_name,
                min(years),
            ), "ok_name"

        return None, "no_year_found"

    except requests.exceptions.RequestException:
        return None, "request_fail"
    except Exception:
        return None, "parse_fail"


def upsert_years(conn, rows):
    sql = """
        INSERT INTO lastfm_artist_year
        (artist_mbid, artist_name, approx_debut_year, fetched_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (artist_mbid) DO UPDATE SET
          artist_name = EXCLUDED.artist_name,
          approx_debut_year = EXCLUDED.approx_debut_year,
          fetched_at = NOW();
    """
    with conn.cursor() as cur:
        execute_batch(cur, sql, rows, page_size=100)
    conn.commit()


def main():
    api_key = load_api_key(API_KEY_PATH)
    conn = psycopg2.connect(DB_DSN)

    migrate(conn)

    artists = fetch_artists(conn, limit=None)
    print(f"Processing {len(artists)} artists\n")

    buffer = []

    searched = found = inserted = 0
    reasons = {
        "ok_mbid": 0,
        "ok_name": 0,
        "name_not_found": 0,
        "rate_limited": 0,
        "http_fail": 0,
        "request_fail": 0,
        "parse_fail": 0,
        "no_year_found": 0,
        "api_error": 0,
    }

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(get_lastfm_year, mbid, name, api_key): (mbid, name)
            for mbid, name in artists
        }

        for i, future in enumerate(
            tqdm(as_completed(futures), total=len(futures)), start=1
        ):
            searched += 1

            try:
                result, reason = future.result()
                reasons[reason] = reasons.get(reason, 0) + 1

                if result:
                    found += 1
                    buffer.append(result)

                if len(buffer) >= UPSERT_BATCH_SIZE:
                    upsert_years(conn, buffer)
                    inserted += len(buffer)
                    buffer.clear()

            except Exception as e:
                print("[FUTURE ERROR]", e)

            if i % PROGRESS_EVERY == 0:
                print(
                    f"[PROGRESS] searched={searched} found={found} "
                    f"inserted={inserted} buffer={len(buffer)} "
                    f"rate_limited={reasons['rate_limited']}"
                )

                if reasons["rate_limited"] > 0:
                    print("[BACKOFF] sleeping 10s")
                    time.sleep(10)

    if buffer:
        upsert_years(conn, buffer)
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
    import sys
    import os

    DB_DSN = "postgres://postgres:baseball162162@localhost:5432/musicbrainz_db?sslmode=disable"
    API_KEY_PATH = "../config/last_fm_keys.json"
    API_KEY = load_api_key(API_KEY_PATH)


    if not API_KEY:
        print("ERROR: Set LASTFM_API_KEY environment variable")
        sys.exit(1)

    # If artists passed via CLI, use them
    if len(sys.argv) > 1:
        artists = sys.argv[1:]
    else:
        # Default test cases
        artists = [
            "Cher",
            "Radiohead",
            "Taylor Swift",
            "Metallica",
            "Adele"
        ]

    print("Testing Last.fm debut year inference\n")

    for artist in artists:
        try:
            year, reason = get_lastfm_year(None, artist, API_KEY)
            if year:
                print(f"{artist:<20} -> {year}")
            else:
                print(f"{artist:<20} -> No year found ({reason})")

        except Exception as e:
            print(f"{artist:<20} -> ERROR: {e}")


# if __name__ == "__main__":
#     main()
