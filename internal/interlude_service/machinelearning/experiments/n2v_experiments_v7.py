"""
Node2Vec v7 Experiments — p/q tuning, epochs, dimensions, walk params.

Run from: /home/jonnym/Desktop/MelodyMap/internal/interlude_service/machinelearning/
    python experiments/n2v_experiments_v7.py

Safety: All experiment embeddings are saved to /tmp/exp_* files.
        Production embeddings and models are NEVER overwritten.
"""
import os
import sys
import time
import json
import warnings
import traceback

import numpy as np
import pandas as pd
import psutil

warnings.filterwarnings("ignore")

# Ensure project root is on path
PROJECT_ROOT = "/home/jonnym/Desktop/MelodyMap/internal/interlude_service/machinelearning"
sys.path.insert(0, PROJECT_ROOT)

from pecanpy import pecanpy as p2v
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    roc_auc_score, average_precision_score, precision_score,
    recall_score, f1_score, accuracy_score, classification_report,
)

# pulearn compatibility shims
import sklearn.utils
if not hasattr(sklearn.utils, "indices_to_mask"):
    def _indices_to_mask(indices, mask_length):
        mask = np.zeros(mask_length, dtype=bool)
        mask[indices] = True
        return mask
    sklearn.utils.indices_to_mask = _indices_to_mask

import sklearn.utils.metaestimators
if not hasattr(sklearn.utils.metaestimators, "if_delegate_has_method"):
    def _if_delegate_has_method(delegate):
        def decorator(fn):
            return fn
        return decorator
    sklearn.utils.metaestimators.if_delegate_has_method = _if_delegate_has_method

from pulearn import ElkanotoPuClassifier

from utils.metrics import l2_normalize
from features.build_features import (
    build_feature_row,
    build_embedding_lookup,
    build_neighbors_dict,
    build_features_for_pairs,
    compute_popularity_interactions,
)
from features.sampling import get_training_test
from utils.database import get_pg_conn

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RESULTS_DIR = os.path.join(PROJECT_ROOT, "experiments", "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

EDGELIST_PATH = "/tmp/exp_artist_edges.edgelist"
EDGES_CSV_PATH = "/tmp/exp_artist_edges.csv"

V6_FEATURES = [
    "cos_sim_src_dst",
    "l2_dist_src_dst",
    "popularity_dst",
    "popularity_src",
    "num_dst_neighbors",
    "max_cos_srcnbr_dst",
    "mean_topk_cos_dstnbr_src",
    "preferential_attachment",
    "adamic_adar",
    "jaccard_neighbors",
    "popularity_ratio",
    "popularity_diff",
    "popularity_product",
    "log_popularity_ratio",
]

V6_BASELINE = {
    "balanced_recall": 0.9283,
    "precision": 0.9684,
    "link_recall": 0.9613,
    "nolink_recall": 0.8953,
    "roc_auc": 0.9839,
}


# ---------------------------------------------------------------------------
# Step 0: Extract edge list from database (once)
# ---------------------------------------------------------------------------
def extract_edges():
    """Extract undirected weighted edges from DB, save CSV + edgelist."""
    if os.path.exists(EDGELIST_PATH) and os.path.exists(EDGES_CSV_PATH):
        print("[edges] Reusing cached edge files.")
        edges_df = pd.read_csv(EDGES_CSV_PATH)
        print(f"[edges] {len(edges_df)} edges, {len(pd.unique(pd.concat([edges_df['src'], edges_df['dst']])))} unique artists")
        return edges_df

    print("[edges] Extracting edges from database...")
    conn = get_pg_conn()
    q = """
        SELECT
            LEAST(artist_id, neighbor_artist_id) AS src,
            GREATEST(artist_id, neighbor_artist_id) AS dst,
            COUNT(*) AS weight
        FROM artist_collab
        WHERE artist_id <> neighbor_artist_id
        GROUP BY 1, 2
    """
    edges_df = pd.read_sql_query(q, conn)
    conn.close()

    edges_df["src"] = edges_df["src"].astype(str)
    edges_df["dst"] = edges_df["dst"].astype(str)

    # Artist -> index mapping
    artists = pd.Index(pd.unique(pd.concat([edges_df["src"], edges_df["dst"]])))
    artist_to_idx = {a: i for i, a in enumerate(artists)}

    edges_df["src_i"] = edges_df["src"].map(artist_to_idx)
    edges_df["dst_i"] = edges_df["dst"].map(artist_to_idx)

    # Save CSV (for neighbor dict later)
    edges_df.to_csv(EDGES_CSV_PATH, index=False)

    # Save edgelist for PecanPy (integer indices)
    edges_df[["src_i", "dst_i", "weight"]].to_csv(
        EDGELIST_PATH, sep=" ", header=False, index=False
    )

    # Save mapping
    idx_to_artist = artists.to_numpy()
    np.save("/tmp/exp_idx_to_artist.npy", idx_to_artist)

    print(f"[edges] {len(edges_df)} edges, {len(artists)} unique artists")
    return edges_df


# ---------------------------------------------------------------------------
# Step 1: Train Node2Vec embeddings
# ---------------------------------------------------------------------------
def train_embeddings(dim=128, num_walks=20, walk_length=20, window=10,
                     epochs=1, p=1.0, q=1.0, workers=2, tag=""):
    """Train PecanPy SparseOTF embeddings and return DataFrame."""
    out_path = f"/tmp/exp_embeddings_{tag}.csv"
    if os.path.exists(out_path):
        print(f"[n2v] Reusing cached embeddings: {out_path}")
        return pd.read_csv(out_path)

    print(f"[n2v] Training: dim={dim}, walks={num_walks}, wl={walk_length}, "
          f"win={window}, epochs={epochs}, p={p}, q={q}, workers={workers}")

    mem_before = psutil.virtual_memory().available / (1024**3)
    print(f"[n2v] Available RAM: {mem_before:.1f} GB")

    t0 = time.time()

    g = p2v.SparseOTF(p=p, q=q, workers=workers, verbose=True)
    g.read_edg(EDGELIST_PATH, weighted=True, directed=False, delimiter=" ")
    print(f"[n2v] Graph: {g.num_nodes} nodes, {g.num_edges} edges")

    embeddings = g.embed(
        dim=dim,
        num_walks=num_walks,
        walk_length=walk_length,
        window_size=window,
        epochs=epochs,
    )

    elapsed = time.time() - t0
    print(f"[n2v] Embedding shape: {embeddings.shape}, time: {elapsed:.0f}s")

    # Map back to artist IDs
    idx_to_artist = np.load("/tmp/exp_idx_to_artist.npy", allow_pickle=True)
    df_emb = pd.DataFrame(
        embeddings, columns=[f"emb_{i}" for i in range(embeddings.shape[1])]
    )
    df_emb["artist_id"] = idx_to_artist

    df_emb.to_csv(out_path, index=False)
    print(f"[n2v] Saved: {out_path}")
    return df_emb


# ---------------------------------------------------------------------------
# Step 2: Build features from embeddings (no DB needed)
# ---------------------------------------------------------------------------
def build_features_from_embeddings(emb_df, edges_df, pairs_df, popularity_map):
    """
    Build the v6 feature set from embedding DataFrame + edge list.
    pairs_df must have columns: src, dst, label.
    popularity_map: dict artist_id(str) -> float popularity_score.
    """
    # Build embedding lookup with popularity
    EMB_COLS = [c for c in emb_df.columns if c.startswith("emb_")]

    embedding_lookup = {}
    for _, row in emb_df.iterrows():
        aid = str(row["artist_id"])
        emb = row[EMB_COLS].to_numpy(dtype=float)
        emb = l2_normalize(emb)
        embedding_lookup[aid] = {
            "emb": emb,
            "popularity": popularity_map.get(aid, 0.0),
        }

    # Build neighbors dict from edges
    neighbors = {}
    for _, row in edges_df.iterrows():
        s, d = str(row["src"]), str(row["dst"])
        neighbors.setdefault(s, set()).add(d)
        neighbors.setdefault(d, set()).add(s)
    # Convert sets to lists
    neighbors = {k: list(v) for k, v in neighbors.items()}

    # Build features
    rows = []
    skipped = 0
    for _, r in pairs_df.iterrows():
        src = str(r["src"])
        dst = str(r["dst"])
        if src not in embedding_lookup or dst not in embedding_lookup:
            skipped += 1
            continue
        feats = build_feature_row(src, dst, embedding_lookup, neighbors, topk=3)
        feats["src"] = src
        feats["dst"] = dst
        feats["label"] = r["label"]
        rows.append(feats)

    print(f"[features] Built {len(rows)} rows, skipped {skipped}")
    df = pd.DataFrame(rows)
    if "popularity_src" in df.columns and "popularity_dst" in df.columns:
        compute_popularity_interactions(df)
    return df


# ---------------------------------------------------------------------------
# Step 3: Sample training pairs from DB
# ---------------------------------------------------------------------------
def get_training_pairs(num_true=100000, neg_ratio=0.30, seed=42):
    """Get training pairs from DB."""
    cache_path = f"/tmp/exp_training_pairs_{num_true}_{neg_ratio}_{seed}.csv"
    if os.path.exists(cache_path):
        print(f"[pairs] Reusing cached pairs: {cache_path}")
        return pd.read_csv(cache_path)

    print(f"[pairs] Sampling {num_true} positive pairs, neg_ratio={neg_ratio}, seed={seed}")
    conn = get_pg_conn()
    pairs = get_training_test(
        conn, num_true_samples=num_true, neg_ratio=neg_ratio,
        random_state=seed, pos_tablesample_pct=5, neg_tablesample_pct=5,
    )
    conn.close()
    pairs.to_csv(cache_path, index=False)
    print(f"[pairs] Got {len(pairs)} pairs: {pairs['label'].value_counts().to_dict()}")
    return pairs


# ---------------------------------------------------------------------------
# Step 4: Get popularity scores from DB
# ---------------------------------------------------------------------------
def get_popularity_map():
    """Fetch artist_id -> popularity_score mapping."""
    cache_path = "/tmp/exp_popularity_map.csv"
    if os.path.exists(cache_path):
        df = pd.read_csv(cache_path)
        return dict(zip(df["artist_id"].astype(str), df["popularity_score"]))

    print("[pop] Fetching popularity scores...")
    conn = get_pg_conn()
    q = """
        SELECT a.id AS artist_id, COALESCE(lfm.popularity_score, 0) AS popularity_score
        FROM artist a
        LEFT JOIN lastfm_artist_stats lfm ON lfm.artist_mbid::text = a.gid::text
    """
    df = pd.read_sql_query(q, conn)
    conn.close()
    df.to_csv(cache_path, index=False)
    print(f"[pop] Got popularity for {len(df)} artists")
    return dict(zip(df["artist_id"].astype(str), df["popularity_score"]))


# ---------------------------------------------------------------------------
# Step 5: Train and evaluate link model
# ---------------------------------------------------------------------------
def train_and_evaluate(features_df, features_list, seed=42, threshold=0.50):
    """Train Elkanoto PU link model, evaluate with threshold sweep."""
    # Filter to valid features
    available = [f for f in features_list if f in features_df.columns]
    missing = set(features_list) - set(available)
    if missing:
        print(f"[model] WARNING: Missing features: {missing}")

    X = features_df[available].values
    y = features_df["label"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=seed, stratify=y
    )

    # Build PU pipeline (matching v6 setup)
    logit = LogisticRegression(
        penalty="elasticnet", solver="saga", max_iter=3000,
        C=1.0, l1_ratio=0.3, random_state=seed,
    )
    pu_clf = ElkanotoPuClassifier(estimator=logit, hold_out_ratio=0.2)
    pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("pu_logit", pu_clf),
    ])

    t0 = time.time()
    pipeline.fit(X_train, y_train)
    train_time = time.time() - t0

    # Predict probabilities
    y_prob_test = pipeline.predict_proba(X_test)
    if y_prob_test.ndim > 1 and y_prob_test.shape[1] > 1:
        y_prob_test = y_prob_test[:, 1]
    y_prob_test = np.clip(y_prob_test, 0.0, 0.994)

    # Threshold sweep
    thresholds = np.arange(0.20, 0.71, 0.05)
    sweep_results = []

    for thr in thresholds:
        y_pred = (y_prob_test >= thr).astype(int)
        link_mask = y_test == 1
        nolink_mask = y_test == 0

        link_recall = recall_score(y_test[link_mask], y_pred[link_mask], zero_division=0) if link_mask.sum() > 0 else 0
        nolink_recall = recall_score(1 - y_test[nolink_mask], 1 - y_pred[nolink_mask], zero_division=0) if nolink_mask.sum() > 0 else 0

        # More direct calculation
        link_recall = (y_pred[link_mask] == 1).sum() / link_mask.sum() if link_mask.sum() > 0 else 0
        nolink_recall = (y_pred[nolink_mask] == 0).sum() / nolink_mask.sum() if nolink_mask.sum() > 0 else 0

        sweep_results.append({
            "threshold": round(thr, 2),
            "precision": precision_score(y_test, y_pred, zero_division=0),
            "link_recall": link_recall,
            "nolink_recall": nolink_recall,
            "balanced_recall": (link_recall + nolink_recall) / 2,
            "f1": f1_score(y_test, y_pred, zero_division=0),
            "accuracy": accuracy_score(y_test, y_pred),
        })

    roc_auc = roc_auc_score(y_test, y_prob_test)
    pr_auc = average_precision_score(y_test, y_prob_test)

    # Find best threshold by balanced recall
    best = max(sweep_results, key=lambda x: x["balanced_recall"])

    return {
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "train_time_s": train_time,
        "best_threshold": best["threshold"],
        "best_precision": best["precision"],
        "best_link_recall": best["link_recall"],
        "best_nolink_recall": best["nolink_recall"],
        "best_balanced_recall": best["balanced_recall"],
        "best_f1": best["f1"],
        "threshold_sweep": sweep_results,
        "n_train": len(y_train),
        "n_test": len(y_test),
        "pos_rate_train": float(y_train.mean()),
        "pos_rate_test": float(y_test.mean()),
    }, pipeline


def print_metrics(label, metrics, baseline=V6_BASELINE):
    """Pretty-print metrics with delta vs baseline."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  ROC AUC:        {metrics['roc_auc']:.4f}  (v6: {baseline['roc_auc']:.4f}, delta: {metrics['roc_auc']-baseline['roc_auc']:+.4f})")
    print(f"  PR AUC:         {metrics['pr_auc']:.4f}")
    print(f"  Precision:      {metrics['best_precision']:.4f}  (v6: {baseline['precision']:.4f}, delta: {metrics['best_precision']-baseline['precision']:+.4f})")
    print(f"  Link Recall:    {metrics['best_link_recall']:.4f}  (v6: {baseline['link_recall']:.4f}, delta: {metrics['best_link_recall']-baseline['link_recall']:+.4f})")
    print(f"  No-Link Recall: {metrics['best_nolink_recall']:.4f}  (v6: {baseline['nolink_recall']:.4f}, delta: {metrics['best_nolink_recall']-baseline['nolink_recall']:+.4f})")
    print(f"  Balanced Recall:{metrics['best_balanced_recall']:.4f}  (v6: {baseline['balanced_recall']:.4f}, delta: {metrics['best_balanced_recall']-baseline['balanced_recall']:+.4f})")
    print(f"  F1:             {metrics['best_f1']:.4f}")
    print(f"  Best Threshold: {metrics['best_threshold']:.2f}")
    print(f"  Train Time:     {metrics['train_time_s']:.1f}s")

    print(f"\n  Threshold Sweep:")
    print(f"  {'Thr':>5} {'Prec':>7} {'LinkR':>7} {'NLinkR':>7} {'BalR':>7} {'F1':>7}")
    for s in metrics["threshold_sweep"]:
        marker = " <-- best" if s["threshold"] == metrics["best_threshold"] else ""
        print(f"  {s['threshold']:5.2f} {s['precision']:7.4f} {s['link_recall']:7.4f} "
              f"{s['nolink_recall']:7.4f} {s['balanced_recall']:7.4f} {s['f1']:7.4f}{marker}")


# ---------------------------------------------------------------------------
# Main experiment runner
# ---------------------------------------------------------------------------
def main():
    all_results = {}

    # ---- SETUP ----
    print("\n" + "="*60)
    print("  SETUP: Extract edges, get pairs, get popularity")
    print("="*60)

    edges_df = extract_edges()
    pairs_df = get_training_pairs(num_true=100000, neg_ratio=0.30, seed=42)
    popularity_map = get_popularity_map()

    # Memory check
    mem = psutil.virtual_memory()
    print(f"\n[mem] Total: {mem.total/(1024**3):.1f} GB, Available: {mem.available/(1024**3):.1f} GB")

    # ================================================================
    # EXP-B: p/q tuning
    # ================================================================
    print("\n" + "#"*60)
    print("#  EXP-B: p/q TUNING")
    print("#"*60)

    pq_configs = [
        ("baseline_p1q1",  1.0, 1.0),
        ("p1_q0.5",        1.0, 0.5),
        ("p1_q2",          1.0, 2.0),
        ("p0.5_q1",        0.5, 1.0),
        ("p2_q0.5",        2.0, 0.5),
    ]

    pq_results = {}
    for tag, p_val, q_val in pq_configs:
        print(f"\n--- EXP-B: {tag} (p={p_val}, q={q_val}) ---")
        try:
            emb_df = train_embeddings(
                dim=128, num_walks=20, walk_length=20, window=10,
                epochs=1, p=p_val, q=q_val, workers=2, tag=f"expB_{tag}",
            )
            feat_df = build_features_from_embeddings(emb_df, edges_df, pairs_df, popularity_map)
            metrics, _ = train_and_evaluate(feat_df, V6_FEATURES, seed=42)
            pq_results[tag] = metrics
            print_metrics(f"EXP-B: {tag}", metrics)
        except Exception as e:
            print(f"[ERROR] {tag}: {e}")
            traceback.print_exc()

    # Pick best p/q by balanced recall
    if pq_results:
        best_pq_tag = max(pq_results, key=lambda k: pq_results[k]["best_balanced_recall"])
        best_pq_config = [c for c in pq_configs if c[0] == best_pq_tag][0]
        best_p, best_q = best_pq_config[1], best_pq_config[2]
        print(f"\n>>> EXP-B WINNER: {best_pq_tag} (p={best_p}, q={best_q}) "
              f"balanced_recall={pq_results[best_pq_tag]['best_balanced_recall']:.4f}")
        all_results["EXP-B"] = pq_results
    else:
        best_p, best_q = 1.0, 1.0
        print("[WARN] No pq results, falling back to p=1, q=1")

    # ================================================================
    # EXP-C: Epochs (1 vs 3)
    # ================================================================
    print("\n" + "#"*60)
    print(f"#  EXP-C: EPOCHS (using p={best_p}, q={best_q})")
    print("#"*60)

    epoch_configs = [
        ("epochs1", 1),
        ("epochs3", 3),
    ]
    epoch_results = {}
    for tag, ep in epoch_configs:
        # Reuse existing if epochs=1 matches best pq
        emb_tag = f"expC_{tag}_p{best_p}_q{best_q}"
        if ep == 1 and best_pq_tag in pq_results:
            # Reuse the pq winner embeddings
            emb_tag_reuse = f"expB_{best_pq_tag}"
            cached = f"/tmp/exp_embeddings_{emb_tag_reuse}.csv"
            if os.path.exists(cached):
                print(f"\n--- EXP-C: {tag} (reusing EXP-B winner) ---")
                epoch_results[tag] = pq_results[best_pq_tag]
                print_metrics(f"EXP-C: {tag}", epoch_results[tag])
                continue

        print(f"\n--- EXP-C: {tag} (epochs={ep}) ---")
        try:
            emb_df = train_embeddings(
                dim=128, num_walks=20, walk_length=20, window=10,
                epochs=ep, p=best_p, q=best_q, workers=2, tag=emb_tag,
            )
            feat_df = build_features_from_embeddings(emb_df, edges_df, pairs_df, popularity_map)
            metrics, _ = train_and_evaluate(feat_df, V6_FEATURES, seed=42)
            epoch_results[tag] = metrics
            print_metrics(f"EXP-C: {tag}", metrics)
        except Exception as e:
            print(f"[ERROR] {tag}: {e}")
            traceback.print_exc()

    if epoch_results:
        best_epoch_tag = max(epoch_results, key=lambda k: epoch_results[k]["best_balanced_recall"])
        best_epochs = [c[1] for c in epoch_configs if c[0] == best_epoch_tag][0]
        print(f"\n>>> EXP-C WINNER: {best_epoch_tag} (epochs={best_epochs}) "
              f"balanced_recall={epoch_results[best_epoch_tag]['best_balanced_recall']:.4f}")
        all_results["EXP-C"] = epoch_results
    else:
        best_epochs = 1

    # ================================================================
    # EXP-A: Dimensions (128 vs 256)
    # ================================================================
    print("\n" + "#"*60)
    print(f"#  EXP-A: DIMENSIONS (p={best_p}, q={best_q}, epochs={best_epochs})")
    print("#"*60)

    dim_configs = [
        ("dim128", 128),
        ("dim256", 256),
    ]
    dim_results = {}
    for tag, dim in dim_configs:
        if dim == 128 and best_epoch_tag in epoch_results:
            # Reuse the epoch winner
            print(f"\n--- EXP-A: {tag} (reusing EXP-C winner) ---")
            dim_results[tag] = epoch_results[best_epoch_tag]
            print_metrics(f"EXP-A: {tag}", dim_results[tag])
            continue

        emb_tag = f"expA_{tag}_p{best_p}_q{best_q}_ep{best_epochs}"
        print(f"\n--- EXP-A: {tag} (dim={dim}) ---")

        # Memory check for dim=256
        mem = psutil.virtual_memory()
        if dim == 256 and mem.available < 3 * (1024**3):
            print(f"[WARN] Only {mem.available/(1024**3):.1f} GB available, skipping dim=256")
            continue

        try:
            emb_df = train_embeddings(
                dim=dim, num_walks=20, walk_length=20, window=10,
                epochs=best_epochs, p=best_p, q=best_q, workers=2, tag=emb_tag,
            )
            feat_df = build_features_from_embeddings(emb_df, edges_df, pairs_df, popularity_map)
            metrics, _ = train_and_evaluate(feat_df, V6_FEATURES, seed=42)
            dim_results[tag] = metrics
            print_metrics(f"EXP-A: {tag}", metrics)
        except Exception as e:
            print(f"[ERROR] {tag}: {e}")
            traceback.print_exc()

    if dim_results:
        best_dim_tag = max(dim_results, key=lambda k: dim_results[k]["best_balanced_recall"])
        best_dim = [c[1] for c in dim_configs if c[0] == best_dim_tag][0]
        print(f"\n>>> EXP-A WINNER: {best_dim_tag} (dim={best_dim}) "
              f"balanced_recall={dim_results[best_dim_tag]['best_balanced_recall']:.4f}")
        all_results["EXP-A"] = dim_results
    else:
        best_dim = 128

    # ================================================================
    # EXP-D: Walk parameters
    # ================================================================
    print("\n" + "#"*60)
    print(f"#  EXP-D: WALK PARAMS (p={best_p}, q={best_q}, epochs={best_epochs}, dim={best_dim})")
    print("#"*60)

    walk_configs = [
        ("wl20_nw20", 20, 20),    # baseline walks
        ("wl40_nw20", 40, 20),    # longer walks
        ("wl20_nw30", 20, 30),    # more walks
    ]

    # Check memory before adding the combined config
    mem = psutil.virtual_memory()
    if mem.available > 4 * (1024**3):
        walk_configs.append(("wl40_nw30", 40, 30))

    walk_results = {}
    for tag, wl, nw in walk_configs:
        if wl == 20 and nw == 20 and best_dim_tag in dim_results:
            print(f"\n--- EXP-D: {tag} (reusing prior winner) ---")
            walk_results[tag] = dim_results[best_dim_tag]
            print_metrics(f"EXP-D: {tag}", walk_results[tag])
            continue

        emb_tag = f"expD_{tag}_p{best_p}_q{best_q}_ep{best_epochs}_d{best_dim}"
        print(f"\n--- EXP-D: {tag} (walk_length={wl}, num_walks={nw}) ---")

        try:
            emb_df = train_embeddings(
                dim=best_dim, num_walks=nw, walk_length=wl, window=10,
                epochs=best_epochs, p=best_p, q=best_q, workers=2, tag=emb_tag,
            )
            feat_df = build_features_from_embeddings(emb_df, edges_df, pairs_df, popularity_map)
            metrics, _ = train_and_evaluate(feat_df, V6_FEATURES, seed=42)
            walk_results[tag] = metrics
            print_metrics(f"EXP-D: {tag}", metrics)
        except Exception as e:
            print(f"[ERROR] {tag}: {e}")
            traceback.print_exc()

    if walk_results:
        best_walk_tag = max(walk_results, key=lambda k: walk_results[k]["best_balanced_recall"])
        best_wl, best_nw = [(wl, nw) for t, wl, nw in walk_configs if t == best_walk_tag][0]
        print(f"\n>>> EXP-D WINNER: {best_walk_tag} (wl={best_wl}, nw={best_nw}) "
              f"balanced_recall={walk_results[best_walk_tag]['best_balanced_recall']:.4f}")
        all_results["EXP-D"] = walk_results
    else:
        best_wl, best_nw = 20, 20

    # ================================================================
    # FINAL: Multi-seed validation of best config
    # ================================================================
    print("\n" + "#"*60)
    print("#  FINAL: MULTI-SEED VALIDATION")
    print(f"#  Config: dim={best_dim}, p={best_p}, q={best_q}, "
          f"epochs={best_epochs}, wl={best_wl}, nw={best_nw}")
    print("#"*60)

    # Retrain embeddings with best params if not already cached
    final_tag = f"v7_final_d{best_dim}_p{best_p}_q{best_q}_ep{best_epochs}_wl{best_wl}_nw{best_nw}"

    # Check if the best walk config embeddings can be reused
    reuse_tag = f"expD_{best_walk_tag}_p{best_p}_q{best_q}_ep{best_epochs}_d{best_dim}"
    reuse_path = f"/tmp/exp_embeddings_{reuse_tag}.csv"
    final_path = f"/tmp/exp_embeddings_{final_tag}.csv"

    if os.path.exists(reuse_path) and not os.path.exists(final_path):
        import shutil
        shutil.copy(reuse_path, final_path)
        print(f"[final] Reused embeddings from {reuse_tag}")

    emb_df = train_embeddings(
        dim=best_dim, num_walks=best_nw, walk_length=best_wl, window=10,
        epochs=best_epochs, p=best_p, q=best_q, workers=2, tag=final_tag,
    )

    seed_results = []
    for seed in [42, 123, 456]:
        print(f"\n--- FINAL: seed={seed} ---")
        pairs = get_training_pairs(num_true=100000, neg_ratio=0.30, seed=seed)
        feat_df = build_features_from_embeddings(emb_df, edges_df, pairs, popularity_map)
        metrics, pipeline = train_and_evaluate(feat_df, V6_FEATURES, seed=seed)
        print_metrics(f"FINAL seed={seed}", metrics)
        seed_results.append({"seed": seed, **metrics})

    # Compute mean metrics
    mean_metrics = {
        "balanced_recall": np.mean([s["best_balanced_recall"] for s in seed_results]),
        "precision": np.mean([s["best_precision"] for s in seed_results]),
        "link_recall": np.mean([s["best_link_recall"] for s in seed_results]),
        "nolink_recall": np.mean([s["best_nolink_recall"] for s in seed_results]),
        "roc_auc": np.mean([s["roc_auc"] for s in seed_results]),
    }

    print("\n" + "="*60)
    print("  V7 MULTI-SEED MEAN vs V6 BASELINE")
    print("="*60)
    for k in ["roc_auc", "precision", "link_recall", "nolink_recall", "balanced_recall"]:
        delta = mean_metrics[k] - V6_BASELINE[k]
        print(f"  {k:20s}: v7={mean_metrics[k]:.4f}  v6={V6_BASELINE[k]:.4f}  delta={delta:+.4f}")

    # Promotion check
    br_pass = mean_metrics["balanced_recall"] > V6_BASELINE["balanced_recall"]
    prec_drop = V6_BASELINE["precision"] - mean_metrics["precision"]
    prec_pass = prec_drop <= 0.05  # max 5 points drop
    promote = br_pass and prec_pass

    print(f"\n  Balanced Recall improved: {br_pass}")
    print(f"  Precision drop: {prec_drop:.4f} (max 0.05): {'PASS' if prec_pass else 'FAIL'}")
    print(f"  PROMOTION DECISION: {'PROMOTE' if promote else 'DO NOT PROMOTE'}")

    # Save final report
    report = {
        "v7_params": {
            "dim": best_dim, "p": best_p, "q": best_q,
            "epochs": best_epochs, "walk_length": best_wl,
            "num_walks": best_nw, "window": 10, "workers": 2,
        },
        "v7_mean_metrics": {k: round(v, 4) for k, v in mean_metrics.items()},
        "v6_baseline": V6_BASELINE,
        "seed_results": seed_results,
        "promotion_pass": promote,
        "experiment_results": {
            "EXP-B_winner": best_pq_tag if pq_results else None,
            "EXP-C_winner": best_epoch_tag if epoch_results else None,
            "EXP-A_winner": best_dim_tag if dim_results else None,
            "EXP-D_winner": best_walk_tag if walk_results else None,
        },
    }

    report_path = os.path.join(RESULTS_DIR, "v7_experiment_report.json")
    # Custom serializer for numpy types
    class NumpyEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, np.bool_):
                return bool(obj)
            return super().default(obj)

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, cls=NumpyEncoder)
    print(f"\nSaved report to {report_path}")

    # Save v7 model artifact (using seed=42 pipeline)
    if promote:
        import joblib
        model_path = os.path.join(
            PROJECT_ROOT, "feature_engineering",
            "logit_model_v7_candidate.joblib"
        )
        # Re-train final model with seed=42 for the artifact
        pairs_42 = get_training_pairs(num_true=100000, neg_ratio=0.30, seed=42)
        feat_42 = build_features_from_embeddings(emb_df, edges_df, pairs_42, popularity_map)
        _, final_pipeline = train_and_evaluate(feat_42, V6_FEATURES, seed=42)

        payload = {
            "model": final_pipeline,
            "threshold": 0.50,
            "feature_names": V6_FEATURES,
            "coef_df": None,
            "pu_method": "elkanoto",
            "n2v_params": report["v7_params"],
        }
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        joblib.dump(payload, model_path)
        print(f"Saved v7 candidate model to {model_path}")

    return report


if __name__ == "__main__":
    report = main()
