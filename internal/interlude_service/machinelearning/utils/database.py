"""
Database utility functions
"""
import psycopg2
import pandas as pd
from typing import List
from config.config import DB_URL


def get_pg_conn():
    """
    Returns a new Postgres connection.
    Caller is responsible for closing it.
    search_path is set via the connection string options in config.py.
    """
    return psycopg2.connect(DB_URL)


def get_artist_collab(conn):
    """Get artist collaboration edges from database"""
    q = """
    SELECT artist_id src, neighbor_artist_id dst
    FROM artist_collab;
    """
    df = pd.read_sql_query(q, con=conn)
    return df


def get_number_hops_data(conn):
    """Get shortest path hop counts between artists"""
    q = """
    SELECT
        start_artist_id src,
        end_artist_id dst,
        num_hops hops
    FROM paths;
    """
    df = pd.read_sql_query(q, conn)
    df.columns = ['src', 'dst', 'hops']
    return df


def get_artist_embeddings(conn, artist_mbids: List[str]):
    """
    Get artist embeddings and popularity scores

    Parameters
    ----------
    conn : psycopg2.connection
        Database connection
    artist_mbids : list
        List of MusicBrainz artist MBID (str)

    Returns
    -------
    pd.DataFrame
        DataFrame with artist_mbid, artist_id, embedding columns, popularity_score
    """
    q = """
    WITH pop_mbid AS (
        SELECT
            a.gid::text AS artist_mbid,
            a.id        AS artist_id,
            lfm.popularity_score
        FROM artist a
        LEFT JOIN lastfm_artist_stats lfm
            ON lfm.artist_mbid::text = a.gid::text
        WHERE a.id = ANY(%s::int[])
    )
    SELECT
        pm.artist_mbid,
        pm.artist_id,
        aen2v.*,
        pm.popularity_score
    FROM pop_mbid pm
    JOIN artist_embeddings_n2v aen2v
        ON aen2v.artist_id = pm.artist_id
    """
    df = pd.read_sql_query(q, con=conn, params=(list(artist_mbids),))
    return df

def get_single_artist_embeddings(artist_id: int):
    """
    Get artist embeddings and popularity scores

    Parameters
    ----------
    conn : psycopg2.connection
        Database connection
    artist_id : int
        List of MusicBrainz artist ID (INT)

    Returns
    -------
    pd.DataFrame
        DataFrame with artist_mbid, artist_id, embedding columns, popularity_score
    """
    
    conn = get_pg_conn()
    q = """
    WITH pop_mbid AS (
        SELECT
            a.gid::text AS artist_mbid,
            a.id        AS artist_id,
            lfm.popularity_score
        FROM artist a
        LEFT JOIN lastfm_artist_stats lfm
            ON lfm.artist_mbid::text = a.gid::text
        WHERE a.id = %s::int
    )
    SELECT
        pm.artist_mbid,
        pm.artist_id,
        aen2v.*,
        pm.popularity_score
    FROM pop_mbid pm
    JOIN artist_embeddings_n2v aen2v
        ON aen2v.artist_id = pm.artist_id
    """
    df = pd.read_sql_query(q, con=conn, params=(artist_id,))
    return df


def get_track_embeddings(conn):
    """Get track-level features from database"""
    q = """
    SELECT *
    FROM artist_features_step2
    """
    df = pd.read_sql_query(q, con=conn)
    return df


def get_artist_k_neighbors_full_random(conn, artist_id: List[str], k: int = 3):
    """
    Get k random neighbors for each artist

    Parameters
    ----------
    conn : psycopg2.connection
        Database connection
    artist_id : list
        List of MusicBrainz artist IDs (INT)
    k : int
        Number of neighbors to sample

    Returns
    -------
    pd.DataFrame
        DataFrame with src_mbid, dst_mbid (dst is neighbor)
    """
    q = """
    WITH src_artists AS (
        SELECT
            id  AS artist_id,
            gid AS artist_mbid
        FROM artist
        WHERE id = ANY(%s::int[])
    ),
    neighbors AS (
        SELECT
            t.artist_id,
            t.neighbor_artist_id
        FROM (
            SELECT
                ac.artist_id,
                ac.neighbor_artist_id,
                ROW_NUMBER() OVER (
                    PARTITION BY ac.artist_id
                    ORDER BY RANDOM()
                ) AS rn
            FROM artist_collab ac
            JOIN src_artists sa
                ON ac.artist_id = sa.artist_id
        ) t
        WHERE t.rn <= %s
    )
    SELECT
        sa.artist_id AS src,
        a_dst.id      AS dst
    FROM neighbors n
    JOIN src_artists sa
        ON sa.artist_id = n.artist_id
    JOIN artist a_dst
        ON a_dst.id = n.neighbor_artist_id
    """
    artist_id = [int(x) for x in artist_id]
    k = int(k)
    # print(artist_id)
    # print(k)
    return pd.read_sql_query(
        q,
        con=conn,
        params=(list(artist_id), k)
    )


def audio_features_join_artist_collab(
    conn: psycopg2.extensions.connection,
    features_table_name: str
) -> pd.DataFrame:
    """
    Returns production-ready, track-level feature data joined to artist collaborations.

    Parameters
    ----------
    conn : psycopg2.connection
        Database connection
    features_table_name : str
        One of:
        - high_level_track_audio_features
        - blocked_high_level_audio_features
        - low_level_track_audio_features
        - blocked_low_level_audio_features

    Returns
    -------
    pd.DataFrame
        Track-level features joined with collaboration data
    """
    allowed_tables = {
        "high_level_track_audio_features",
        "blocked_high_level_audio_features",
        "low_level_track_audio_features",
        "blocked_low_level_audio_features",
    }

    if features_table_name not in allowed_tables:
        raise ValueError(f"Invalid features table: {features_table_name}")

    q = f"""
    WITH acfl AS (
        SELECT
            a1.gid AS src_artist_gid,
            a2.gid AS dst_artist_gid,
            r.gid  AS recording_gid
        FROM artist_collab ac
        JOIN artist a1 ON a1.id = ac.artist_id
        JOIN artist a2 ON a2.id = ac.neighbor_artist_id
        JOIN recording r ON r.id = ac.recording_id
    )
    SELECT
        acfl.src_artist_gid src,
        acfl.dst_artist_gid dst,
        acfl.recording_gid,
        af.*
    FROM acfl
    JOIN {features_table_name} af
      ON af.recording_gid = acfl.recording_gid;
    """

    return pd.read_sql_query(q, con=conn)
