"""
Extract artist collaboration edges from database
"""
import pandas as pd
from utils.database import get_pg_conn, get_artist_collab
from config.config import ARTIST_EDGES_CSV


def extract_artist_edges():
    """
    Extract artist collaboration edges from database and save to CSV

    Returns
    -------
    pd.DataFrame
        Artist collaboration edges (src, dst, weight)
    """
    print("Connecting to database...")
    conn = get_pg_conn()

    print("Extracting artist collaboration edges...")
    artist_collab = get_artist_collab(conn)

    conn.close()

    # Aggregate by edge to get weights
    print("Aggregating edges by weight...")
    edges_df = (
        artist_collab
        .assign(weight=1)
        .groupby(['src', 'dst'], as_index=False)
        .agg({'weight': 'sum'})
    )

    print(f"Total edges extracted: {len(edges_df)}")

    # Save to CSV
    edges_df.to_csv(ARTIST_EDGES_CSV, index=False)
    print(f"Saved to {ARTIST_EDGES_CSV}")

    return edges_df


if __name__ == "__main__":
    extract_artist_edges()
