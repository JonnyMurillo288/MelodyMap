"""
Generate Node2Vec embeddings for artist collaboration graph
"""
import os
import numpy as np
import pandas as pd
from pecanpy import pecanpy as p2v
from sklearn.decomposition import PCA
import plotly.express as px

from config.config import (
    ARTIST_EDGES_CSV,
    ARTIST_EDGES_EDGELIST,
    ARTIST_EMBEDDINGS_CSV,
    IDX_TO_ARTIST_NPY,
    NODE2VEC_DIM,
    NODE2VEC_NUM_WALKS,
    NODE2VEC_WALK_LENGTH,
    NODE2VEC_WINDOW_SIZE,
    NODE2VEC_EPOCHS,
    NODE2VEC_P,
    NODE2VEC_Q,
    NODE2VEC_WORKERS
)


def generate_embeddings(visualize=False, n_sample_viz=20000):
    """
    Generate Node2Vec embeddings using PecanPy

    Parameters
    ----------
    visualize : bool
        Whether to create visualization
    n_sample_viz : int
        Number of samples to use for visualization

    Returns
    -------
    pd.DataFrame
        Embeddings DataFrame with artist_id and embedding columns
    """
    print("Loading edges from CSV...")
    artist_collab_n2v = pd.read_csv(ARTIST_EDGES_CSV)

    # Deduplicate edges
    print("Deduplicating edges...")
    edges_df = (
        artist_collab_n2v
        .dropna(subset=["src", "dst"])
        .astype({"src": str, "dst": str})
        .groupby(["src", "dst"], as_index=False)
        .agg({"weight": "sum"})
    )

    # Create artist <-> index mapping
    print("Creating artist ID mapping...")
    artists = pd.Index(
        pd.unique(pd.concat([edges_df["src"], edges_df["dst"]]))
    )

    artist_to_idx = {a: i for i, a in enumerate(artists)}
    idx_to_artist = artists.to_numpy()

    # Persist mapping
    np.save(IDX_TO_ARTIST_NPY, idx_to_artist)
    print(f"Mapped {len(idx_to_artist)} artists")
    print(f"Saved mapping to {IDX_TO_ARTIST_NPY}")

    # Rewrite edge list with integer indices
    print("Rewriting edges with integer indices...")
    edges_df["src_i"] = edges_df["src"].map(artist_to_idx)
    edges_df["dst_i"] = edges_df["dst"].map(artist_to_idx)

    edges_df[["src_i", "dst_i", "weight"]].to_csv(
        ARTIST_EDGES_EDGELIST,
        sep=" ",
        header=False,
        index=False
    )
    print(f"Wrote {len(edges_df)} edges to {ARTIST_EDGES_EDGELIST}")

    # Load graph into PecanPy
    print("Loading graph into PecanPy...")
    g = p2v.SparseOTF(
        p=NODE2VEC_P,
        q=NODE2VEC_Q,
        workers=NODE2VEC_WORKERS,
        verbose=True
    )

    g.read_edg(
        ARTIST_EDGES_EDGELIST,
        weighted=True,
        directed=False,
        delimiter=" "
    )

    print(f"Graph loaded - Nodes: {g.num_nodes}, Edges: {g.num_edges}")
    assert g.num_nodes == len(idx_to_artist), "Node count mismatch!"

    # Train Node2Vec
    print("Training Node2Vec embeddings...")
    embeddings = g.embed(
        dim=NODE2VEC_DIM,
        num_walks=NODE2VEC_NUM_WALKS,
        walk_length=NODE2VEC_WALK_LENGTH,
        window_size=NODE2VEC_WINDOW_SIZE,
        epochs=NODE2VEC_EPOCHS
    )

    print(f"Embedding matrix shape: {embeddings.shape}")

    # Assign embeddings back to artist IDs
    df_emb = pd.DataFrame(
        embeddings,
        columns=[f"emb_{i}" for i in range(embeddings.shape[1])]
    )
    df_emb["artist_id"] = idx_to_artist

    print(f"Final embedding table: {df_emb.shape}")

    # Visualization
    if visualize:
        print("Creating visualization...")
        N_SAMPLE = min(n_sample_viz, len(df_emb))
        df_sample = df_emb.sample(n=N_SAMPLE, random_state=42)

        X = df_sample.filter(like="emb_").values
        X_2d = PCA(n_components=2, random_state=42).fit_transform(X)

        df_sample["pc1"] = X_2d[:, 0]
        df_sample["pc2"] = X_2d[:, 1]

        fig = px.scatter(
            df_sample,
            x="pc1",
            y="pc2",
            hover_data=["artist_id"],
            title="Artist Collaboration Embeddings (Node2Vec / PecanPy)",
            opacity=0.6
        )

        fig.update_traces(marker=dict(size=4))
        fig.update_layout(width=900, height=900)
        fig.show()

    # Save embeddings
    df_emb.to_csv(ARTIST_EMBEDDINGS_CSV, index=False)
    print(f"Saved embeddings to {ARTIST_EMBEDDINGS_CSV}")

    return df_emb


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate Node2Vec embeddings")
    parser.add_argument("--visualize", action="store_true", help="Create visualization")
    parser.add_argument("--n-sample-viz", type=int, default=20000,
                       help="Number of samples for visualization")

    args = parser.parse_args()

    generate_embeddings(visualize=args.visualize, n_sample_viz=args.n_sample_viz)
