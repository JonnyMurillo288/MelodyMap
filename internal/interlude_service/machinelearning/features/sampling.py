"""
Sampling utilities for creating training datasets
"""

import pandas as pd
import psycopg2
import psycopg2.extensions


def get_training_test(
    conn: psycopg2.extensions.connection,
    num_true_samples: int,
    neg_ratio: float = 0.15,
    random_state: int = 42,
    pos_tablesample_pct: int = 2,
    neg_tablesample_pct: int = 2,
) -> pd.DataFrame:
    """
    Construct a labeled training dataset for artist–artist link prediction.

    This function samples a set of positive edges (existing collaborations)
    and negative edges (artist pairs that do not exist in the collaboration graph),
    returning a shuffled DataFrame suitable for supervised binary classification.

    Sampling is performed using PostgreSQL TABLESAMPLE to ensure scalability
    and approximate randomness without full-table scans or ORDER BY RANDOM().

    Parameters
    ----------
    conn : psycopg2.extensions.connection
        Open PostgreSQL connection to a database containing the `artist_collab` table.

    num_true_samples : int
        Number of positive (existing) artist–artist edges to sample.
        This value is a target; fewer rows may be returned if the TABLESAMPLE
        percentage is too small.

    neg_ratio : float, default=0.15
        Ratio of negative samples to positive samples.
        For example, 0.15 generates one negative edge for every ~7 positives.

    random_state : int, default=42
        Random seed used for reproducible TABLESAMPLE queries and final shuffling.

    pos_tablesample_pct : int, default=2
        Percentage of table blocks to scan when sampling positive edges.
        Higher values increase randomness and reliability but cost more I/O.

    neg_tablesample_pct : int, default=2
        Percentage of table blocks to scan when building the artist pool
        for negative edge sampling.

    Returns
    -------
    pd.DataFrame
        Shuffled DataFrame with the following columns:

        - src (int): Source artist ID (undirected, min ID)
        - dst (int): Destination artist ID (undirected, max ID)
        - label (int): Edge label
            - 1 = existing collaboration (positive)
            - 0 = non-existent collaboration (negative)

    Guarantees
    ----------
    - All positive edges exist in `artist_collab`
    - All negative edges are guaranteed not to exist in `artist_collab`
    - Undirected edges are normalized (src < dst)
    - No ORDER BY RANDOM() is used
    - No full graph is materialized in Python memory
    - Sampling is bounded, scalable, and reproducible

    Raises
    ------
    ValueError
        If input parameters are invalid.

    RuntimeError
        If insufficient positive or negative samples can be generated
        due to low TABLESAMPLE percentages or high graph density.
    """


    if num_true_samples <= 0:
        raise ValueError("num_true_samples must be > 0")

    if not (0 < neg_ratio < 10):
        raise ValueError("neg_ratio must be sensible (e.g. 0.1–5.0)")

    # --------------------------------------------------
    # 1. POSITIVE EDGES (fast, approximate random)
    # --------------------------------------------------
    q_pos = f"""
        SELECT
            LEAST(artist_id, neighbor_artist_id) AS src,
            GREATEST(artist_id, neighbor_artist_id) AS dst
        FROM artist_collab
        TABLESAMPLE SYSTEM ({pos_tablesample_pct})
        REPEATABLE ({random_state})
        GROUP BY 1, 2
        LIMIT %s;
    """

    df_pos = pd.read_sql_query(q_pos, conn, params=(num_true_samples,))
    if df_pos.empty:
        raise RuntimeError("No positive edges sampled; increase TABLESAMPLE pct")

    df_pos["label"] = 1

    # --------------------------------------------------
    # 2. NEGATIVE EDGES (pure SQL, guaranteed non-edges)
    # --------------------------------------------------
    num_neg_samples = int(len(df_pos) * neg_ratio)
    if num_neg_samples == 0:
        return df_pos.sample(frac=1, random_state=random_state).reset_index(drop=True)

    q_neg = f"""
        WITH artist_pool AS (
            SELECT DISTINCT artist_id
            FROM artist_collab
            TABLESAMPLE SYSTEM ({neg_tablesample_pct})
            REPEATABLE ({random_state})
        )
        SELECT
            LEAST(a.artist_id, b.artist_id) AS src,
            GREATEST(a.artist_id, b.artist_id) AS dst
        FROM artist_pool a
        JOIN artist_pool b
          ON a.artist_id < b.artist_id
        WHERE NOT EXISTS (
            SELECT 1
            FROM artist_collab ac
            WHERE LEAST(ac.artist_id, ac.neighbor_artist_id) = LEAST(a.artist_id, b.artist_id)
              AND GREATEST(ac.artist_id, ac.neighbor_artist_id) = GREATEST(a.artist_id, b.artist_id)
        )
        LIMIT %s;
    """

    df_neg = pd.read_sql_query(q_neg, conn, params=(num_neg_samples,))
    if df_neg.empty:
        raise RuntimeError(
            "No negative edges sampled; increase neg TABLESAMPLE pct"
        )

    df_neg["label"] = 0

    # --------------------------------------------------
    # 3. COMBINE + SHUFFLE
    # --------------------------------------------------
    df = (
        pd.concat([df_pos, df_neg], ignore_index=True)
        .sample(frac=1, random_state=random_state)
        .reset_index(drop=True)
    )
    

    return df
