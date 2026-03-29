"""
Feature engineering pipeline for track prediction
"""
import pandas as pd
from utils.database import (
    get_pg_conn,
    get_artist_collab,
    get_artist_embeddings,
    get_artist_k_neighbors_full_random
)
from features.build_features import (
    build_embedding_lookup,
    build_neighbors_dict,
    build_features_for_pairs
)
from features.sampling import get_training_test
from config.config import ARTIST_COLLAB_NEG_CSV

import psycopg2
import pandas as pd

def audio_features_join_artist_collab(
    conn: psycopg2.extensions.connection,
    features_table_name: str
) -> pd.DataFrame:
    """
    Returns production-ready, track-level feature data joined to artist collaborations.

    Parameters
    ----------
    features_table_name : str
        One of:
        - high_level_track_audio_features
        - blocked_high_level_audio_features
        - low_level_track_audio_features
        - blocked_low_level_audio_features
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

