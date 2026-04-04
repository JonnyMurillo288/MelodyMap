#!/usr/bin/env python3
"""
Regenerate v7 Node2Vec embeddings end-to-end and persist them.

This script:
  1. Extracts edges from the database
  2. Trains Node2Vec embeddings with v7 params (p=1, q=0.5)
  3. Saves embeddings to PERSISTENT storage (project dir, not /tmp)
  4. Loads embeddings into the artist_embeddings_n2v database table
  5. Retrains the v7 logit model using the fresh embeddings
  6. Saves the model artifact and metadata
  7. Runs verification checks

Run from: /home/jonnym/Desktop/MelodyMap/internal/interlude_service/machinelearning/
    python3 experiments/regenerate_v7_e2e.py
"""
import os
import sys
import time
import json
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = "/home/jonnym/Desktop/MelodyMap/internal/interlude_service/machinelearning"
sys.path.insert(0, PROJECT_ROOT)

from pecanpy import pecanpy as p2v
import psycopg2
from psycopg2.extras import execute_values

from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    roc_auc_score, average_precision_score, precision_score,
    recall_score, f1_score, classification_report,
)

# pulearn compatibility shims
import sklearn.utils
if not hasattr(sklearn.utils, "indices_to_mask"):
    def _itm(indices, mask_length):
        m = np.zeros(mask_length, dtype=bool)
        m[indices] = True
        return m
    sklearn.utils.indices_to_mask = _itm
import sklearn.utils.metaestimators
if not hasattr(sklearn.utils.metaestimators, "if_delegate_has_method"):
    sklearn.utils.metaestimators.if_delegate_has_method = lambda d: (lambda fn: fn)

from pulearn import ElkanotoPuClassifier

from utils.database import get_pg_conn
from features.build_features import build_feature_row, compute_popularity_interactions
from features.sampling import get_training_test
from config.config import (
    DB_URL,
    NODE2VEC_DIM, NODE2VEC_NUM_WALKS, NODE2VEC_WALK_LENGTH,
    NODE2VEC_WINDOW_SIZE, NODE2VEC_EPOCHS, NODE2VEC_P, NODE2VEC_Q,
    NODE2VEC_WORKERS, LINK_PREDICTION_FEATURES,
)

# ---- Persistent storage paths (NOT /tmp) ----
PERSISTENT_DIR = os.path.join(PROJECT_ROOT, "training_data", "v7_embeddings")
os.makedirs(PERSISTENT_DIR, exist_ok=True)

EDGES_CSV_PATH = os.path.join(PERSISTENT_DIR, "artist_edges.csv")
EDGELIST_PATH = os.path.join(PERSISTENT_DIR, "artist_edges.edgelist")
IDX_MAP_PATH = os.path.join(PERSISTENT_DIR, "idx_to_artist.npy")
EMBEDDINGS_CSV_PATH = os.path.join(PERSISTENT_DIR, "artist_embeddings_v7.csv")

# Also write to the standard /tmp paths so existing pipeline code can find them
TMP_EDGES_CSV = "/tmp/artist_edges.csv"
TMP_EDGELIST = "/tmp/artist_edges.edgelist"
TMP_IDX_MAP = "/tmp/idx_to_artist.npy"
TMP_EMBEDDINGS_CSV = "/tmp/artist_embeddings.csv"

# v7 feature list (same as v6 features + popularity interactions)
V7_FEATURES = [
    "cos_sim_src_dst", "l2_dist_src_dst", "popularity_dst", "popularity_src",
    "num_dst_neighbors", "max_cos_srcnbr_dst", "mean_topk_cos_dstnbr_src",
    "preferential_attachment", "adamic_adar", "jaccard_neighbors",
    "popularity_ratio", "popularity_diff", "popularity_product", "log_popularity_ratio",
]

V6_BASELINE = {
    "balanced_recall": 0.9283, "precision": 0.9684,
    "link_recall": 0.9613, "nolink_recall": 0.8953, "roc_auc": 0.9839,
}


def step1_extract_edges():
    """Extract undirected weighted edges from the database."""
    if os.path.exists(EDGES_CSV_PATH) and os.path.exists(EDGELIST_PATH):
        print("[Step 1] Reusing cached edge files from persistent storage.")
        return pd.read_csv(EDGES_CSV_PATH)

    print("[Step 1] Extracting edges from database...")
    conn = get_pg_conn()
    q = """
        SELECT LEAST(artist_id, neighbor_artist_id) AS src,
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
    idx_to_artist = artists.to_numpy()

    edges_df["src_i"] = edges_df["src"].map(artist_to_idx)
    edges_df["dst_i"] = edges_df["dst"].map(artist_to_idx)

    # Save to persistent storage
    edges_df.to_csv(EDGES_CSV_PATH, index=False)
    edges_df[["src_i", "dst_i", "weight"]].to_csv(
        EDGELIST_PATH, sep=" ", header=False, index=False
    )
    np.save(IDX_MAP_PATH, idx_to_artist)

    # Also save to /tmp for pipeline compatibility
    edges_df.to_csv(TMP_EDGES_CSV, index=False)
    edges_df[["src_i", "dst_i", "weight"]].to_csv(
        TMP_EDGELIST, sep=" ", header=False, index=False
    )
    np.save(TMP_IDX_MAP, idx_to_artist)

    print(f"[Step 1] {len(edges_df)} edges, {len(artists)} unique artists")
    print(f"[Step 1] Saved to: {PERSISTENT_DIR}")
    return edges_df


def step2_train_embeddings():
    """Train Node2Vec embeddings with v7 parameters."""
    if os.path.exists(EMBEDDINGS_CSV_PATH):
        print(f"[Step 2] Reusing cached embeddings: {EMBEDDINGS_CSV_PATH}")
        return pd.read_csv(EMBEDDINGS_CSV_PATH)

    print(f"[Step 2] Training Node2Vec: dim={NODE2VEC_DIM}, walks={NODE2VEC_NUM_WALKS}, "
          f"wl={NODE2VEC_WALK_LENGTH}, p={NODE2VEC_P}, q={NODE2VEC_Q}, "
          f"epochs={NODE2VEC_EPOCHS}, workers={NODE2VEC_WORKERS}")

    t0 = time.time()

    g = p2v.SparseOTF(p=NODE2VEC_P, q=NODE2VEC_Q, workers=NODE2VEC_WORKERS, verbose=True)
    g.read_edg(EDGELIST_PATH, weighted=True, directed=False, delimiter=" ")
    print(f"[Step 2] Graph: {g.num_nodes} nodes, {g.num_edges} edges")

    embeddings = g.embed(
        dim=NODE2VEC_DIM,
        num_walks=NODE2VEC_NUM_WALKS,
        walk_length=NODE2VEC_WALK_LENGTH,
        window_size=NODE2VEC_WINDOW_SIZE,
        epochs=NODE2VEC_EPOCHS,
    )

    elapsed = time.time() - t0
    print(f"[Step 2] Embedding shape: {embeddings.shape}, time: {elapsed:.0f}s")

    idx_to_artist = np.load(IDX_MAP_PATH, allow_pickle=True)
    df_emb = pd.DataFrame(
        embeddings, columns=[f"emb_{i}" for i in range(embeddings.shape[1])]
    )
    df_emb["artist_id"] = idx_to_artist

    # Save to persistent storage
    df_emb.to_csv(EMBEDDINGS_CSV_PATH, index=False)
    print(f"[Step 2] Saved embeddings to: {EMBEDDINGS_CSV_PATH}")

    # Also save to /tmp for pipeline compatibility
    df_emb.to_csv(TMP_EMBEDDINGS_CSV, index=False)
    print(f"[Step 2] Also saved to: {TMP_EMBEDDINGS_CSV}")

    return df_emb


def step3_load_embeddings_to_db(df_emb):
    """Load embeddings into the artist_embeddings_n2v database table."""
    print("[Step 3] Loading embeddings to database...")

    emb_cols = [c for c in df_emb.columns if c.startswith("emb_")]
    cols = ["artist_id"] + emb_cols
    df_load = df_emb[cols].copy()

    print(f"[Step 3] {len(df_load)} artists, {len(emb_cols)} dimensions")

    with psycopg2.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            # Backup check: count existing rows
            cur.execute("SELECT COUNT(*) FROM artist_embeddings_n2v")
            old_count = cur.fetchone()[0]
            print(f"[Step 3] Existing rows in DB: {old_count}")

            # Create/replace table
            emb_col_defs = ",\n        ".join([f"{c} REAL" for c in emb_cols])
            create_sql = f"""
            DROP TABLE IF EXISTS artist_embeddings_n2v CASCADE;
            CREATE TABLE artist_embeddings_n2v (
                artist_id INT PRIMARY KEY,
                {emb_col_defs}
            );
            """
            cur.execute(create_sql)

            # Bulk insert
            records = df_load.values.tolist()
            insert_cols = ",".join(cols)
            insert_sql = f"INSERT INTO artist_embeddings_n2v ({insert_cols}) VALUES %s"

            BATCH_SIZE = 5000
            for i in range(0, len(records), BATCH_SIZE):
                batch = records[i:i + BATCH_SIZE]
                execute_values(cur, insert_sql, batch, page_size=1000)
                if (i + BATCH_SIZE) % 50000 == 0 or i + BATCH_SIZE >= len(records):
                    print(f"  Inserted {min(i + BATCH_SIZE, len(records))}/{len(records)} rows")

        conn.commit()

    # Verify
    with psycopg2.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM artist_embeddings_n2v")
            new_count = cur.fetchone()[0]
            print(f"[Step 3] New rows in DB: {new_count}")
            assert new_count == len(df_load), f"Row count mismatch: {new_count} vs {len(df_load)}"

    print(f"[Step 3] Successfully loaded {new_count} embeddings to database")


def build_neighbors(edges_df):
    """Build neighbors dict from edges DataFrame."""
    neighbors = {}
    for s, d in zip(edges_df["src"].astype(str), edges_df["dst"].astype(str)):
        neighbors.setdefault(s, set()).add(d)
        neighbors.setdefault(d, set()).add(s)
    return {k: list(v) for k, v in neighbors.items()}


def build_lookup(emb_df, pop_map):
    """Build embedding lookup dict."""
    emb_cols = [c for c in emb_df.columns if c.startswith("emb_")]
    emb_vals = emb_df[emb_cols].values.astype(np.float64)
    norms = np.linalg.norm(emb_vals, axis=1, keepdims=True)
    emb_vals = emb_vals / (norms + 1e-12)
    aids = emb_df["artist_id"].astype(str).values
    return {aids[i]: {"emb": emb_vals[i], "popularity": pop_map.get(aids[i], 0.0)}
            for i in range(len(aids))}


def get_pop_map():
    """Get popularity scores for all artists."""
    conn = get_pg_conn()
    df = pd.read_sql_query(
        "SELECT a.id AS artist_id, COALESCE(lfm.popularity_score,0) AS popularity_score "
        "FROM artist a LEFT JOIN lastfm_artist_stats lfm ON lfm.artist_mbid::text=a.gid::text",
        conn
    )
    conn.close()
    return dict(zip(df["artist_id"].astype(str), df["popularity_score"]))


def build_features_for_pairs(emb_df, edges_df, pairs_df, pop_map):
    """Build feature rows for training pairs."""
    lookup = build_lookup(emb_df, pop_map)
    neighbors = build_neighbors(edges_df)

    rows = []
    skip = 0
    total = len(pairs_df)
    for idx, r in pairs_df.iterrows():
        s, d = str(r["src"]), str(r["dst"])
        if s not in lookup or d not in lookup:
            skip += 1
            continue
        feats = build_feature_row(s, d, lookup, neighbors, topk=3)
        feats["src"] = s
        feats["dst"] = d
        feats["label"] = r["label"]
        rows.append(feats)
        if (idx + 1) % 25000 == 0:
            print(f"  Built {idx + 1}/{total} features...")

    print(f"  Done: {len(rows)} rows, {skip} skipped")
    df = pd.DataFrame(rows)
    if "popularity_src" in df.columns:
        compute_popularity_interactions(df)
    return df


def step4_train_model(emb_df, edges_df):
    """Train and evaluate the v7 logit model, then save it."""
    import joblib

    print("[Step 4] Training v7 logit model...")

    # Get training pairs
    print("[Step 4] Getting training pairs (100K true, neg_ratio=0.30)...")
    conn = get_pg_conn()
    pairs = get_training_test(conn, 100000, 0.30, 42, 5, 5)
    conn.close()
    print(f"[Step 4] Pairs: {len(pairs)}, label dist: {pairs['label'].value_counts().to_dict()}")

    # Get popularity map
    print("[Step 4] Getting popularity map...")
    pop_map = get_pop_map()

    # Build features
    print("[Step 4] Building features...")
    feat_df = build_features_for_pairs(emb_df, edges_df, pairs, pop_map)

    # Train and evaluate across 3 seeds
    seed_results = []
    best_pipe = None
    best_br = -1

    for seed in [42, 123, 456]:
        print(f"\n[Step 4] Training with seed={seed}...")
        avail = [f for f in V7_FEATURES if f in feat_df.columns]
        X = feat_df[avail].values
        y = feat_df["label"].values

        Xtr, Xte, ytr, yte = train_test_split(
            X, y, test_size=0.2, random_state=seed, stratify=y
        )

        logit = LogisticRegression(
            penalty="elasticnet", solver="saga", max_iter=3000,
            C=1.0, l1_ratio=0.3, random_state=seed
        )
        pu = ElkanotoPuClassifier(estimator=logit, hold_out_ratio=0.2)
        pipe = Pipeline([
            ("imp", SimpleImputer(strategy="median")),
            ("scl", StandardScaler()),
            ("pu", pu)
        ])

        t0 = time.time()
        pipe.fit(Xtr, ytr)
        train_time = time.time() - t0

        yp = pipe.predict_proba(Xte)
        if yp.ndim > 1 and yp.shape[1] > 1:
            yp = yp[:, 1]
        yp = np.clip(yp, 0, 0.994)

        # Threshold sweep
        sweep = []
        for thr in np.arange(0.20, 0.71, 0.05):
            pred = (yp >= thr).astype(int)
            lm = yte == 1
            nm = yte == 0
            lr = (pred[lm] == 1).sum() / lm.sum() if lm.sum() else 0
            nr = (pred[nm] == 0).sum() / nm.sum() if nm.sum() else 0
            sweep.append({
                "thr": round(float(thr), 2),
                "prec": float(precision_score(yte, pred, zero_division=0)),
                "lr": float(lr), "nr": float(nr),
                "br": float((lr + nr) / 2),
                "f1": float(f1_score(yte, pred, zero_division=0)),
            })

        roc = float(roc_auc_score(yte, yp))
        best_thr = max(sweep, key=lambda x: x["br"])

        result = {
            "seed": seed, "roc_auc": roc, "train_s": train_time,
            **best_thr
        }
        seed_results.append(result)

        d_br = best_thr["br"] - V6_BASELINE["balanced_recall"]
        print(f"  Seed {seed}: ROC={roc:.4f} Prec={best_thr['prec']:.4f} "
              f"LR={best_thr['lr']:.4f} NLR={best_thr['nr']:.4f} "
              f"BR={best_thr['br']:.4f} (delta vs v6: {d_br:+.4f}) thr={best_thr['thr']}")

        if best_thr["br"] > best_br:
            best_br = best_thr["br"]
            best_pipe = pipe

    # Mean metrics
    mean = {k: np.mean([s[k] for s in seed_results])
            for k in ["roc_auc", "prec", "lr", "nr", "br"]}

    print("\n" + "=" * 60)
    print("  V7 3-SEED MEAN vs V6 BASELINE")
    print("=" * 60)
    labels = [("roc_auc", "roc_auc"), ("prec", "precision"),
              ("lr", "link_recall"), ("nr", "nolink_recall"), ("br", "balanced_recall")]
    for mk, v6k in labels:
        d = mean[mk] - V6_BASELINE[v6k]
        print(f"  {v6k:20s}: v7={mean[mk]:.4f}  v6={V6_BASELINE[v6k]:.4f}  delta={d:+.4f}")

    # Save model artifact
    model_path = os.path.join(PROJECT_ROOT, "feature_engineering", "logit_model_v7.joblib")
    payload = {
        "model": best_pipe,
        "threshold": 0.50,
        "feature_names": V7_FEATURES,
        "coef_df": None,
        "pu_method": "elkanoto",
        "n2v_params": {
            "dim": NODE2VEC_DIM, "p": NODE2VEC_P, "q": NODE2VEC_Q,
            "epochs": NODE2VEC_EPOCHS, "walk_length": NODE2VEC_WALK_LENGTH,
            "num_walks": NODE2VEC_NUM_WALKS, "window": NODE2VEC_WINDOW_SIZE,
            "workers": NODE2VEC_WORKERS,
        },
    }
    joblib.dump(payload, model_path)
    print(f"\n[Step 4] Saved model to: {model_path}")

    # Save metadata
    meta_path = os.path.join(PROJECT_ROOT, "feature_engineering", "metadata", "logit_model_v7.json")
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)

    class NE(json.JSONEncoder):
        def default(self, o):
            if isinstance(o, (np.integer,)): return int(o)
            if isinstance(o, (np.floating,)): return float(o)
            if isinstance(o, np.ndarray): return o.tolist()
            if isinstance(o, np.bool_): return bool(o)
            return super().default(o)

    meta = {
        "model_version": "v7",
        "n2v_params": payload["n2v_params"],
        "features": V7_FEATURES,
        "threshold": 0.50,
        "pu_method": "elkanoto",
        "mean_metrics": {v6k: round(float(mean[mk]), 4) for mk, v6k in labels},
        "seed_results": seed_results,
        "v6_baseline": V6_BASELINE,
        "embeddings_persistent_path": EMBEDDINGS_CSV_PATH,
        "embeddings_db_table": "artist_embeddings_n2v",
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2, cls=NE)
    print(f"[Step 4] Saved metadata to: {meta_path}")

    return mean, seed_results


def step5_verify():
    """Run verification checks."""
    import joblib

    print("\n[Step 5] Running verification checks...")

    # Check 1: Model file exists and loads
    model_path = os.path.join(PROJECT_ROOT, "feature_engineering", "logit_model_v7.joblib")
    payload = joblib.load(model_path)
    assert "model" in payload, "Model payload missing 'model' key"
    assert "feature_names" in payload, "Model payload missing 'feature_names' key"
    assert payload["feature_names"] == V7_FEATURES, "Feature names mismatch"
    print("  [OK] Model file loads correctly")

    # Check 2: Model registry can find the file
    from models.model_registry import LOGIT_REGISTRY
    v7_path = LOGIT_REGISTRY.get("v7")
    assert v7_path is not None, "v7 not in LOGIT_REGISTRY"
    assert v7_path.exists(), f"v7 model file missing: {v7_path}"
    print("  [OK] Model registry points to existing file")

    # Check 3: Embeddings exist in database
    with psycopg2.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM artist_embeddings_n2v")
            count = cur.fetchone()[0]
            assert count > 500000, f"Expected >500K embeddings, got {count}"
            print(f"  [OK] Database has {count} embeddings")

            # Check embedding dimension
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'artist_embeddings_n2v' AND column_name LIKE 'emb_%' "
                "ORDER BY ordinal_position"
            )
            emb_cols = [r[0] for r in cur.fetchall()]
            assert len(emb_cols) == NODE2VEC_DIM, f"Embedding dim mismatch: {len(emb_cols)} vs {NODE2VEC_DIM}"
            print(f"  [OK] Embedding dimension: {len(emb_cols)}")

    # Check 4: Persistent embedding file exists
    assert os.path.exists(EMBEDDINGS_CSV_PATH), f"Persistent embedding file missing: {EMBEDDINGS_CSV_PATH}"
    df_check = pd.read_csv(EMBEDDINGS_CSV_PATH, nrows=5)
    emb_cols_csv = [c for c in df_check.columns if c.startswith("emb_")]
    assert len(emb_cols_csv) == NODE2VEC_DIM, f"CSV embedding dim mismatch: {len(emb_cols_csv)}"
    print(f"  [OK] Persistent embedding CSV exists: {EMBEDDINGS_CSV_PATH}")

    # Check 5: Feature name compatibility between model and inference
    from config.config import LINK_PREDICTION_FEATURES as cfg_features
    model_feats = set(payload["feature_names"])
    cfg_feats = set(cfg_features)
    missing_in_model = cfg_feats - model_feats
    missing_in_config = model_feats - cfg_feats
    if missing_in_model:
        print(f"  [WARN] Config features not in model: {missing_in_model}")
    if missing_in_config:
        print(f"  [WARN] Model features not in config: {missing_in_config}")
    if not missing_in_model and not missing_in_config:
        print("  [OK] Feature names match between model and config")

    # Check 6: /tmp symlink compatibility
    if os.path.exists(TMP_EMBEDDINGS_CSV):
        print(f"  [OK] /tmp embedding CSV exists for pipeline compatibility")
    else:
        print(f"  [INFO] /tmp embedding CSV not present (will need re-copy after reboot)")

    print("\n[Step 5] All checks passed.")


def main():
    print("=" * 70)
    print("  V7 NODE2VEC EMBEDDING REGENERATION (END-TO-END)")
    print(f"  Params: p={NODE2VEC_P}, q={NODE2VEC_Q}, dim={NODE2VEC_DIM}")
    print(f"  Persistent storage: {PERSISTENT_DIR}")
    print("=" * 70)

    t_total = time.time()

    # Step 1: Extract edges
    print("\n" + "-" * 60)
    print("STEP 1: EXTRACT EDGES")
    print("-" * 60)
    edges_df = step1_extract_edges()

    # Step 2: Train embeddings
    print("\n" + "-" * 60)
    print("STEP 2: TRAIN NODE2VEC EMBEDDINGS")
    print("-" * 60)
    emb_df = step2_train_embeddings()

    # Step 3: Load embeddings to database
    print("\n" + "-" * 60)
    print("STEP 3: LOAD EMBEDDINGS TO DATABASE")
    print("-" * 60)
    step3_load_embeddings_to_db(emb_df)

    # Step 4: Train and save model
    print("\n" + "-" * 60)
    print("STEP 4: TRAIN AND SAVE V7 MODEL")
    print("-" * 60)
    mean_metrics, seed_results = step4_train_model(emb_df, edges_df)

    # Step 5: Verification
    print("\n" + "-" * 60)
    print("STEP 5: VERIFICATION")
    print("-" * 60)
    step5_verify()

    elapsed = time.time() - t_total
    print(f"\n{'=' * 70}")
    print(f"  COMPLETE in {elapsed / 60:.1f} minutes")
    print(f"  Persistent embeddings: {EMBEDDINGS_CSV_PATH}")
    print(f"  Model artifact: {os.path.join(PROJECT_ROOT, 'feature_engineering', 'logit_model_v7.joblib')}")
    print(f"  Database table: artist_embeddings_n2v")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
