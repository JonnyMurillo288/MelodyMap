"""
Feature engineering for artist hop prediction and link prediction
"""
import numpy as np
import pandas as pd
from collections import defaultdict
from typing import Dict, List
from tqdm import tqdm

from utils.metrics import l2_normalize


def compute_popularity_interactions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Derive popularity interaction features from existing popularity_src and
    popularity_dst columns.  The result is written back into *df* in-place and
    the same DataFrame is returned for convenience.

    Features added
    --------------
    popularity_ratio        max(src, dst) / (min(src, dst) + 1e-8)
    popularity_diff         |src - dst|
    popularity_product      src * dst
    log_popularity_ratio    log1p(popularity_ratio)

    These are additive -- callers that load an older model simply ignore the
    extra columns via model.feature_names selection.
    """
    pop_src = df["popularity_src"]
    pop_dst = df["popularity_dst"]

    pop_max = np.maximum(pop_src, pop_dst)
    pop_min = np.minimum(pop_src, pop_dst)

    df["popularity_ratio"] = pop_max / (pop_min + 1e-8)
    df["popularity_diff"] = np.abs(pop_src - pop_dst)
    df["popularity_product"] = pop_src * pop_dst
    df["log_popularity_ratio"] = np.log1p(df["popularity_ratio"])

    return df


def build_feature_row(src, dst, embedding_lookup, neighbors, topk=3):
    """
    Build feature row for a src-dst pair
    Artist Embeddings

    Parameters
    ----------
    src : str
        Source artist ID
    dst : str
        Destination artist ID
    embedding_lookup : dict
        Mapping from artist ID to embedding dictionary
    neighbors : dict
        Mapping from artist ID to list of neighbor IDs
    topk : int
        Number of top neighbors to use for aggregation

    Returns
    -------
    dict
        Dictionary of features
    """

    # Embeddings
    src_emb = embedding_lookup[src]["emb"]
    dst_emb = embedding_lookup[dst]["emb"]

    diff = np.abs(src_emb - dst_emb)

    feats = {
        # Global geometry
        "cos_sim_src_dst": float(src_emb @ dst_emb),
        "l2_dist_src_dst": float(np.linalg.norm(src_emb - dst_emb)),
        "dot_src_dst": float(src_emb @ dst_emb),
        "abs_diff_mean": float(diff.mean()),
        "abs_diff_max": float(diff.max()),

        # Popularity priors
        "popularity_src": embedding_lookup[src].get("popularity", 0.0),
        "popularity_dst": embedding_lookup[dst].get("popularity", 0.0),
    }

    # One-hop: src → dst
    src_nbrs = [n for n in neighbors.get(src, []) if n in embedding_lookup]

    if src_nbrs:
        src_nbr_embs = np.vstack([embedding_lookup[n]["emb"] for n in src_nbrs])
        cos_vals = src_nbr_embs @ dst_emb
        topk_vals = np.sort(cos_vals)[-min(topk, len(cos_vals)):]

        feats.update({
            "max_cos_srcnbr_dst": float(cos_vals.max()),
            "mean_cos_srcnbr_dst": float(cos_vals.mean()),
            "mean_topk_cos_srcnbr_dst": float(topk_vals.mean()),
            "num_src_neighbors": len(src_nbrs),
        })
    else:
        feats.update({
            "max_cos_srcnbr_dst": 0.0,
            "mean_cos_srcnbr_dst": 0.0,
            "mean_topk_cos_srcnbr_dst": 0.0,
            "num_src_neighbors": 0,
        })

    # One-hop: dst → src
    dst_nbrs = [n for n in neighbors.get(dst, []) if n in embedding_lookup]

    if dst_nbrs:
        dst_nbr_embs = np.vstack([embedding_lookup[n]["emb"] for n in dst_nbrs])
        cos_vals = dst_nbr_embs @ src_emb
        topk_vals = np.sort(cos_vals)[-min(topk, len(cos_vals)):]

        feats.update({
            "max_cos_dstnbr_src": float(cos_vals.max()),
            "mean_cos_dstnbr_src": float(cos_vals.mean()),
            "mean_topk_cos_dstnbr_src": float(topk_vals.mean()),
            "num_dst_neighbors": len(dst_nbrs),
        })
    else:
        feats.update({
            "max_cos_dstnbr_src": 0.0,
            "mean_cos_dstnbr_src": 0.0,
            "mean_topk_cos_dstnbr_src": 0.0,
            "num_dst_neighbors": 0,
        })

    # Two-hop graph features
    src_set = set(neighbors.get(src, []))
    dst_set = set(neighbors.get(dst, []))

    shared = src_set & dst_set
    num_shared = len(shared)

    deg_src = len(src_set)
    deg_dst = len(dst_set)

    # Adamic–Adar
    adamic_adar = 0.0
    for n in shared:
        deg_n = len(neighbors.get(n, []))
        if deg_n > 1:
            adamic_adar += 1.0 / np.log(deg_n + 1)

    feats.update({
        "shared_neighbors": num_shared,
        "jaccard_neighbors": (
            num_shared / (deg_src + deg_dst - num_shared)
            if (deg_src + deg_dst - num_shared) > 0 else 0.0
        ),
        "adamic_adar": float(adamic_adar),
        "preferential_attachment": deg_src * deg_dst,
    })

    return feats


def build_embedding_lookup(embeddings_df: pd.DataFrame) -> Dict:
    """
    Build embedding lookup dictionary

    Parameters
    ----------
    embeddings_df : pd.DataFrame
        DataFrame with artist_mbid, embedding columns, popularity_score

    Returns
    -------
    dict
        Mapping from artist_mbid to {"emb": array, "popularity": float}
    """
    EMB_COLS = [c for c in embeddings_df.columns if c.startswith("emb_")]

    embedding_lookup = {
        row["artist_id"]: {
            "emb": row[EMB_COLS].to_numpy(dtype=float),
            "popularity": row["popularity_score"] if "popularity_score" in row else 0.0,
        }
        for _, row in embeddings_df.iterrows()
    }

    # L2 normalize embeddings
    for v in embedding_lookup.values():
        v["emb"] = l2_normalize(v["emb"])

    return embedding_lookup


def build_neighbors_dict(neighbors_df: pd.DataFrame) -> Dict[str, List[str]]:
    """
    Build neighbors dictionary from edge list

    Parameters
    ----------
    neighbors_df : pd.DataFrame
        DataFrame with src, dst columns

    Returns
    -------
    dict
        Mapping from artist ID to list of unique neighbor IDs
    """
    neighbors = defaultdict(list)

    for _, row in neighbors_df.iterrows():
        neighbors[row["src"]].append(row["dst"])
        neighbors[row["src"]] = list(set(neighbors[row["src"]]))

    return neighbors


def build_features_for_pairs(
    pairs_df: pd.DataFrame,
    embedding_lookup: Dict,
    neighbors: Dict,
    target_col: str = None,
    topk: int = 3,
    verbose: bool = True
) -> pd.DataFrame:
    """
    Build features for all src-dst pairs

    Parameters
    ----------
    pairs_df : pd.DataFrame
        DataFrame with src, dst columns and optional target column
    embedding_lookup : dict
        Artist ID to embedding mapping
    neighbors : dict
        Artist ID to neighbors mapping
    target_col : str, optional
        Name of target column in pairs_df
    topk : int
        Number of top neighbors to use
    verbose : bool
        Show progress bar

    Returns
    -------
    pd.DataFrame
        DataFrame with features for each pair
    """
    rows = []

    iterator = pairs_df.iterrows()
    if verbose:
        iterator = tqdm(iterator, total=len(pairs_df), desc="Building features")

    bad = 0
    for _, r in iterator:
        src = r["src"]
        dst = r["dst"]
        if src not in embedding_lookup or dst not in embedding_lookup:
            bad += 1
            continue

        feats = build_feature_row(
            src=src,
            dst=dst,
            embedding_lookup=embedding_lookup,
            neighbors=neighbors,
            topk=topk,
        )

        feats["src"] = src
        feats["dst"] = dst

        if target_col and target_col in r:
            feats[target_col] = r[target_col]
        # breakpoint()
        rows.append(feats)

    print("Number of skipped src,dst is",bad,round(bad/len(pairs_df)))
    df_features = pd.DataFrame(rows)

    # Derive popularity interaction features so they are available for all
    # model versions.  Older models simply ignore the extra columns.
    if "popularity_src" in df_features.columns and "popularity_dst" in df_features.columns:
        compute_popularity_interactions(df_features)

    return df_features
