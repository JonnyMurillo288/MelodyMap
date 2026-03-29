"""
Feature engineering pipeline for hop prediction
"""
import pandas as pd
from utils.database import (
    get_pg_conn,
    get_number_hops_data,
    get_artist_embeddings,
    get_artist_k_neighbors_full_random
)
from features.build_features import (
    build_embedding_lookup,
    build_neighbors_dict,
    build_features_for_pairs
)
from config.config import EMBEDDINGS_FEATURES_CSV, Y_FEATURES_CSV


def build_hop_prediction_features():
    """
    Build features for hop prediction task

    Returns
    -------
    tuple
        (X_df, y_series) - Features and target
    """
    print("Connecting to database...")
    conn = get_pg_conn()

    print("Loading hop count data...")
    num_hops = get_number_hops_data(conn)
    print(f"Loaded {len(num_hops)} artist pairs with hop counts")

    print("Loading artist embeddings and popularity...")
    embeddings_src = get_artist_embeddings(conn, num_hops.src.tolist())
    embeddings_dst = get_artist_embeddings(conn, num_hops.dst.tolist())
    embeddings = pd.concat([embeddings_src, embeddings_dst])

    print("Sampling k neighbors for each artist...")
    neighbors_src = get_artist_k_neighbors_full_random(conn, num_hops.src.tolist(), k=3)
    neighbors_dst = get_artist_k_neighbors_full_random(conn, num_hops.dst.tolist(), k=3)
    artist_collab_3 = pd.concat([neighbors_src, neighbors_dst])
    artist_collab_3 = artist_collab_3.rename(
        columns={
            artist_collab_3.columns[0]: "src",
            artist_collab_3.columns[1]: "dst",
        }
    )

    print("Getting embeddings for neighbor artists...")
    neighbor_embeddings = get_artist_embeddings(conn, artist_collab_3.dst.tolist())
    embeddings = pd.concat([embeddings, neighbor_embeddings])

    conn.close()

    print("Building embedding lookup...")
    embedding_lookup = build_embedding_lookup(embeddings)

    print("Building neighbors dictionary...")
    neighbors = build_neighbors_dict(artist_collab_3)

    print(f"Building features for {len(num_hops)} pairs...")
    df_features = build_features_for_pairs(
        pairs_df=num_hops,
        embedding_lookup=embedding_lookup,
        neighbors=neighbors,
        target_col='hops',
        topk=3,
        verbose=True
    )

    print(f"Generated {len(df_features)} feature rows")

    # Split features and target
    y = df_features['hops']
    X = df_features.drop(columns=['hops', 'src', 'dst'])

    # Save to CSV
    X.to_csv(EMBEDDINGS_FEATURES_CSV, index=False)
    y.to_csv(Y_FEATURES_CSV, index=False)
    print(f"Saved X features to {EMBEDDINGS_FEATURES_CSV}")
    print(f"Saved y target to {Y_FEATURES_CSV}")

    return X, y


if __name__ == "__main__":
    X, y = build_hop_prediction_features()
    print(f"\nFeature shape: {X.shape}")
    print(f"Target shape: {y.shape}")
    print(f"\nTarget distribution:\n{y.value_counts().sort_index()}")
