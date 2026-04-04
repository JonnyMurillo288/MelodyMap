"""
Fast Node2Vec screening -- uses 10 walks (instead of 20) and 30K pairs for
initial p/q ranking. Winner gets validated with full 20 walks + 130K pairs.

Run from: /home/jonnym/Desktop/MelodyMap/internal/interlude_service/machinelearning/
    python experiments/n2v_fast_screen.py
"""
import os, sys, time, json, warnings, traceback
import numpy as np
import pandas as pd
import psutil

warnings.filterwarnings("ignore")

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
    recall_score, f1_score, accuracy_score,
)

import sklearn.utils
if not hasattr(sklearn.utils, "indices_to_mask"):
    def _itm(indices, mask_length):
        m = np.zeros(mask_length, dtype=bool); m[indices] = True; return m
    sklearn.utils.indices_to_mask = _itm
import sklearn.utils.metaestimators
if not hasattr(sklearn.utils.metaestimators, "if_delegate_has_method"):
    sklearn.utils.metaestimators.if_delegate_has_method = lambda d: (lambda fn: fn)

from pulearn import ElkanotoPuClassifier
from utils.metrics import l2_normalize
from features.build_features import build_feature_row, compute_popularity_interactions
from features.sampling import get_training_test
from utils.database import get_pg_conn

RESULTS_DIR = os.path.join(PROJECT_ROOT, "experiments", "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

EDGELIST_PATH = "/tmp/exp_artist_edges.edgelist"
EDGES_CSV_PATH = "/tmp/exp_artist_edges.csv"

V6_FEATURES = [
    "cos_sim_src_dst", "l2_dist_src_dst", "popularity_dst", "popularity_src",
    "num_dst_neighbors", "max_cos_srcnbr_dst", "mean_topk_cos_dstnbr_src",
    "preferential_attachment", "adamic_adar", "jaccard_neighbors",
    "popularity_ratio", "popularity_diff", "popularity_product", "log_popularity_ratio",
]

V6_BASELINE = {
    "balanced_recall": 0.9283, "precision": 0.9684,
    "link_recall": 0.9613, "nolink_recall": 0.8953, "roc_auc": 0.9839,
}


def extract_edges():
    if os.path.exists(EDGELIST_PATH) and os.path.exists(EDGES_CSV_PATH):
        print("[edges] Cached.")
        return pd.read_csv(EDGES_CSV_PATH)

    print("[edges] Extracting...")
    conn = get_pg_conn()
    q = """
        SELECT LEAST(artist_id, neighbor_artist_id) AS src,
               GREATEST(artist_id, neighbor_artist_id) AS dst,
               COUNT(*) AS weight
        FROM artist_collab WHERE artist_id <> neighbor_artist_id GROUP BY 1, 2
    """
    edges_df = pd.read_sql_query(q, conn); conn.close()
    edges_df["src"] = edges_df["src"].astype(str)
    edges_df["dst"] = edges_df["dst"].astype(str)

    artists = pd.Index(pd.unique(pd.concat([edges_df["src"], edges_df["dst"]])))
    a2i = {a: i for i, a in enumerate(artists)}
    edges_df["src_i"] = edges_df["src"].map(a2i)
    edges_df["dst_i"] = edges_df["dst"].map(a2i)
    edges_df.to_csv(EDGES_CSV_PATH, index=False)
    edges_df[["src_i", "dst_i", "weight"]].to_csv(EDGELIST_PATH, sep=" ", header=False, index=False)
    np.save("/tmp/exp_idx_to_artist.npy", artists.to_numpy())
    print(f"[edges] {len(edges_df)} edges, {len(artists)} artists")
    return edges_df


def train_embeddings(dim, num_walks, walk_length, window, epochs, p, q, workers, tag):
    out = f"/tmp/exp_embeddings_{tag}.csv"
    if os.path.exists(out):
        print(f"[n2v] Cached: {tag}")
        return pd.read_csv(out)

    print(f"[n2v] Training {tag}: dim={dim} walks={num_walks} wl={walk_length} "
          f"ep={epochs} p={p} q={q} w={workers}")
    t0 = time.time()

    g = p2v.SparseOTF(p=p, q=q, workers=workers, verbose=True)
    g.read_edg(EDGELIST_PATH, weighted=True, directed=False, delimiter=" ")
    print(f"[n2v] {g.num_nodes} nodes, {g.num_edges} edges")

    emb = g.embed(dim=dim, num_walks=num_walks, walk_length=walk_length,
                  window_size=window, epochs=epochs)
    elapsed = time.time() - t0
    print(f"[n2v] Done in {elapsed:.0f}s, shape={emb.shape}")

    idx2a = np.load("/tmp/exp_idx_to_artist.npy", allow_pickle=True)
    df = pd.DataFrame(emb, columns=[f"emb_{i}" for i in range(emb.shape[1])])
    df["artist_id"] = idx2a
    df.to_csv(out, index=False)
    return df


def build_neighbors_fast(edges_df):
    """Build neighbors dict efficiently."""
    neighbors = {}
    for s, d in zip(edges_df["src"].astype(str), edges_df["dst"].astype(str)):
        neighbors.setdefault(s, set()).add(d)
        neighbors.setdefault(d, set()).add(s)
    return {k: list(v) for k, v in neighbors.items()}


def build_embedding_lookup_fast(emb_df, pop_map):
    """Build lookup dict from embedding DataFrame."""
    EMB_COLS = [c for c in emb_df.columns if c.startswith("emb_")]
    emb_vals = emb_df[EMB_COLS].values
    # L2 normalize
    norms = np.linalg.norm(emb_vals, axis=1, keepdims=True)
    emb_vals = emb_vals / (norms + 1e-12)

    aids = emb_df["artist_id"].astype(str).values
    lookup = {}
    for i in range(len(aids)):
        lookup[aids[i]] = {"emb": emb_vals[i], "popularity": pop_map.get(aids[i], 0.0)}
    return lookup


def build_features_fast(emb_df, edges_df, pairs_df, pop_map):
    """Build features for pairs."""
    lookup = build_embedding_lookup_fast(emb_df, pop_map)
    neighbors = build_neighbors_fast(edges_df)

    rows = []
    skip = 0
    for _, r in pairs_df.iterrows():
        s, d = str(r["src"]), str(r["dst"])
        if s not in lookup or d not in lookup:
            skip += 1; continue
        feats = build_feature_row(s, d, lookup, neighbors, topk=3)
        feats["src"] = s; feats["dst"] = d; feats["label"] = r["label"]
        rows.append(feats)

    print(f"[feat] {len(rows)} rows, {skip} skipped")
    df = pd.DataFrame(rows)
    if "popularity_src" in df.columns:
        compute_popularity_interactions(df)
    return df


def get_pairs(n_true, neg_ratio, seed):
    cache = f"/tmp/exp_training_pairs_{n_true}_{neg_ratio}_{seed}.csv"
    if os.path.exists(cache):
        return pd.read_csv(cache)
    conn = get_pg_conn()
    pairs = get_training_test(conn, n_true, neg_ratio, seed, 5, 5)
    conn.close()
    pairs.to_csv(cache, index=False)
    print(f"[pairs] {len(pairs)} pairs")
    return pairs


def get_pop_map():
    cache = "/tmp/exp_popularity_map.csv"
    if os.path.exists(cache):
        df = pd.read_csv(cache)
        return dict(zip(df["artist_id"].astype(str), df["popularity_score"]))
    conn = get_pg_conn()
    df = pd.read_sql_query(
        "SELECT a.id AS artist_id, COALESCE(lfm.popularity_score,0) AS popularity_score "
        "FROM artist a LEFT JOIN lastfm_artist_stats lfm ON lfm.artist_mbid::text=a.gid::text", conn)
    conn.close()
    df.to_csv(cache, index=False)
    return dict(zip(df["artist_id"].astype(str), df["popularity_score"]))


def train_eval(features_df, feats_list, seed=42):
    avail = [f for f in feats_list if f in features_df.columns]
    X = features_df[avail].values
    y = features_df["label"].values
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=seed, stratify=y)

    logit = LogisticRegression(penalty="elasticnet", solver="saga", max_iter=3000,
                               C=1.0, l1_ratio=0.3, random_state=seed)
    pu = ElkanotoPuClassifier(estimator=logit, hold_out_ratio=0.2)
    pipe = Pipeline([("imp", SimpleImputer(strategy="median")),
                     ("scl", StandardScaler()), ("pu", pu)])
    t0 = time.time()
    pipe.fit(Xtr, ytr)
    tt = time.time() - t0

    yp = pipe.predict_proba(Xte)
    if yp.ndim > 1 and yp.shape[1] > 1: yp = yp[:, 1]
    yp = np.clip(yp, 0, 0.994)

    sweep = []
    for thr in np.arange(0.20, 0.71, 0.05):
        pred = (yp >= thr).astype(int)
        lm = yte == 1; nm = yte == 0
        lr = (pred[lm] == 1).sum() / lm.sum() if lm.sum() else 0
        nr = (pred[nm] == 0).sum() / nm.sum() if nm.sum() else 0
        sweep.append({"thr": round(thr, 2),
                       "prec": precision_score(yte, pred, zero_division=0),
                       "lr": lr, "nr": nr, "br": (lr + nr) / 2,
                       "f1": f1_score(yte, pred, zero_division=0)})

    roc = roc_auc_score(yte, yp)
    pr = average_precision_score(yte, yp)
    best = max(sweep, key=lambda x: x["br"])

    return {"roc_auc": roc, "pr_auc": pr, "train_s": tt,
            "thr": best["thr"], "prec": best["prec"],
            "lr": best["lr"], "nr": best["nr"], "br": best["br"],
            "f1": best["f1"], "sweep": sweep}, pipe


def show(label, m):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  ROC={m['roc_auc']:.4f} Prec={m['prec']:.4f} LR={m['lr']:.4f} "
          f"NLR={m['nr']:.4f} BR={m['br']:.4f} F1={m['f1']:.4f} thr={m['thr']:.2f}")
    d = m['br'] - V6_BASELINE['balanced_recall']
    print(f"  Delta BR vs v6: {d:+.4f}")
    print(f"  {'Thr':>5} {'Prec':>6} {'LR':>6} {'NLR':>6} {'BR':>6} {'F1':>6}")
    for s in m["sweep"]:
        mk = " *" if s["thr"] == m["thr"] else ""
        print(f"  {s['thr']:5.2f} {s['prec']:6.4f} {s['lr']:6.4f} {s['nr']:6.4f} {s['br']:6.4f} {s['f1']:6.4f}{mk}")


def main():
    edges_df = extract_edges()
    # Use fewer pairs for fast screening
    pairs_screen = get_pairs(30000, 0.30, seed=42)
    pop_map = get_pop_map()

    mem = psutil.virtual_memory()
    print(f"[mem] Available: {mem.available/(1024**3):.1f} GB")

    # ======== EXP-B: p/q tuning with 10 walks (screening) ========
    print("\n" + "#"*60)
    print("#  EXP-B: p/q SCREENING (10 walks, 30K pairs)")
    print("#"*60)

    pq_configs = [
        ("b_p1q1",   1.0, 1.0),
        ("b_p1q05",  1.0, 0.5),
        ("b_p1q2",   1.0, 2.0),
        ("b_p05q1",  0.5, 1.0),
        ("b_p2q05",  2.0, 0.5),
    ]

    pq_results = {}
    for tag, pv, qv in pq_configs:
        print(f"\n--- {tag} (p={pv}, q={qv}) ---")
        try:
            emb = train_embeddings(128, 10, 20, 10, 1, pv, qv, 2, f"screen_{tag}")
            feat = build_features_fast(emb, edges_df, pairs_screen, pop_map)
            met, _ = train_eval(feat, V6_FEATURES, seed=42)
            pq_results[tag] = met
            show(f"EXP-B screen: {tag}", met)
        except Exception as e:
            print(f"[ERR] {tag}: {e}"); traceback.print_exc()

    if not pq_results:
        print("No pq results!"); return

    best_pq = max(pq_results, key=lambda k: pq_results[k]["br"])
    bp, bq = [(p, q) for t, p, q in pq_configs if t == best_pq][0]
    print(f"\n>>> EXP-B SCREEN WINNER: {best_pq} (p={bp}, q={bq}) BR={pq_results[best_pq]['br']:.4f}")

    # ======== Validate winner with 20 walks, 100K pairs ========
    print("\n" + "#"*60)
    print(f"#  EXP-B VALIDATION: p={bp}, q={bq}, 20 walks, 100K pairs")
    print("#"*60)

    pairs_full = get_pairs(100000, 0.30, seed=42)

    emb_full = train_embeddings(128, 20, 20, 10, 1, bp, bq, 2, f"full_p{bp}_q{bq}")
    feat_full = build_features_fast(emb_full, edges_df, pairs_full, pop_map)
    met_full, _ = train_eval(feat_full, V6_FEATURES, seed=42)
    show(f"EXP-B FULL: p={bp}, q={bq}", met_full)

    # Also validate baseline p=1,q=1 with full walks if different
    if bp != 1.0 or bq != 1.0:
        emb_base = train_embeddings(128, 20, 20, 10, 1, 1.0, 1.0, 2, "expB_baseline_p1q1")
        feat_base = build_features_fast(emb_base, edges_df, pairs_full, pop_map)
        met_base, _ = train_eval(feat_base, V6_FEATURES, seed=42)
        show("EXP-B FULL BASELINE: p=1, q=1", met_base)

        # Decide if winner still wins
        if met_full["br"] > met_base["br"]:
            print(f"\n>>> EXP-B CONFIRMED: p={bp}, q={bq} beats baseline")
        else:
            print(f"\n>>> EXP-B: Baseline (p=1,q=1) wins on full validation")
            bp, bq = 1.0, 1.0
            met_full = met_base

    # ======== EXP-C: Epochs ========
    print("\n" + "#"*60)
    print(f"#  EXP-C: EPOCHS (p={bp}, q={bq})")
    print("#"*60)

    emb_ep3 = train_embeddings(128, 20, 20, 10, 3, bp, bq, 2, f"expC_ep3_p{bp}_q{bq}")
    feat_ep3 = build_features_fast(emb_ep3, edges_df, pairs_full, pop_map)
    met_ep3, _ = train_eval(feat_ep3, V6_FEATURES, seed=42)
    show(f"EXP-C: epochs=3, p={bp}, q={bq}", met_ep3)

    best_ep = 3 if met_ep3["br"] > met_full["br"] else 1
    met_ep_winner = met_ep3 if best_ep == 3 else met_full
    print(f"\n>>> EXP-C WINNER: epochs={best_ep} BR={met_ep_winner['br']:.4f}")

    # ======== EXP-A: Dimensions ========
    print("\n" + "#"*60)
    print(f"#  EXP-A: DIM 256 (p={bp}, q={bq}, ep={best_ep})")
    print("#"*60)

    mem = psutil.virtual_memory()
    if mem.available > 3 * 1024**3:
        emb256 = train_embeddings(256, 20, 20, 10, best_ep, bp, bq, 2,
                                   f"expA_d256_p{bp}_q{bq}_ep{best_ep}")
        feat256 = build_features_fast(emb256, edges_df, pairs_full, pop_map)
        met256, _ = train_eval(feat256, V6_FEATURES, seed=42)
        show(f"EXP-A: dim=256", met256)

        best_dim = 256 if met256["br"] > met_ep_winner["br"] else 128
        met_dim_winner = met256 if best_dim == 256 else met_ep_winner
    else:
        print(f"[WARN] Only {mem.available/(1024**3):.1f} GB available, skipping dim=256")
        best_dim = 128
        met_dim_winner = met_ep_winner

    print(f"\n>>> EXP-A WINNER: dim={best_dim} BR={met_dim_winner['br']:.4f}")

    # ======== EXP-D: Walk params ========
    print("\n" + "#"*60)
    print(f"#  EXP-D: WALK PARAMS (d={best_dim}, p={bp}, q={bq}, ep={best_ep})")
    print("#"*60)

    walk_configs = [
        ("wl40_nw20", 40, 20),
        ("wl20_nw30", 20, 30),
    ]
    walk_results = {"wl20_nw20": met_dim_winner}

    for tag, wl, nw in walk_configs:
        emb = train_embeddings(best_dim, nw, wl, 10, best_ep, bp, bq, 2,
                                f"expD_{tag}_d{best_dim}_p{bp}_q{bq}_ep{best_ep}")
        feat = build_features_fast(emb, edges_df, pairs_full, pop_map)
        met, _ = train_eval(feat, V6_FEATURES, seed=42)
        walk_results[tag] = met
        show(f"EXP-D: {tag}", met)

    best_walk = max(walk_results, key=lambda k: walk_results[k]["br"])
    best_wl = {"wl20_nw20": 20, "wl40_nw20": 40, "wl20_nw30": 20}[best_walk]
    best_nw = {"wl20_nw20": 20, "wl40_nw20": 20, "wl20_nw30": 30}[best_walk]
    print(f"\n>>> EXP-D WINNER: {best_walk} (wl={best_wl}, nw={best_nw}) "
          f"BR={walk_results[best_walk]['br']:.4f}")

    # ======== FINAL: 3-seed validation ========
    print("\n" + "#"*60)
    print(f"#  FINAL: 3-SEED VALIDATION")
    print(f"#  d={best_dim} p={bp} q={bq} ep={best_ep} wl={best_wl} nw={best_nw}")
    print("#"*60)

    final_tag = f"v7_d{best_dim}_p{bp}_q{bq}_ep{best_ep}_wl{best_wl}_nw{best_nw}"
    # Reuse existing embedding if params match
    emb_final = train_embeddings(best_dim, best_nw, best_wl, 10, best_ep, bp, bq, 2, final_tag)

    seed_results = []
    for seed in [42, 123, 456]:
        print(f"\n--- Seed={seed} ---")
        pairs = get_pairs(100000, 0.30, seed=seed)
        feat = build_features_fast(emb_final, edges_df, pairs, pop_map)
        met, pipe = train_eval(feat, V6_FEATURES, seed=seed)
        show(f"Seed {seed}", met)
        seed_results.append({"seed": seed, **met})

    # Mean metrics
    mean = {k: np.mean([s[k] for s in seed_results])
            for k in ["roc_auc", "prec", "lr", "nr", "br"]}

    print("\n" + "="*60)
    print("  V7 MULTI-SEED MEAN vs V6 BASELINE")
    print("="*60)
    labels = [("roc_auc", "roc_auc"), ("prec", "precision"),
              ("lr", "link_recall"), ("nr", "nolink_recall"), ("br", "balanced_recall")]
    for mk, v6k in labels:
        d = mean[mk] - V6_BASELINE[v6k]
        print(f"  {v6k:20s}: v7={mean[mk]:.4f}  v6={V6_BASELINE[v6k]:.4f}  delta={d:+.4f}")

    br_pass = mean["br"] > V6_BASELINE["balanced_recall"]
    prec_drop = V6_BASELINE["precision"] - mean["prec"]
    prec_pass = prec_drop <= 0.05
    promote = br_pass and prec_pass

    print(f"\n  BR improved: {br_pass}")
    print(f"  Precision drop: {prec_drop:.4f} ({'PASS' if prec_pass else 'FAIL'})")
    print(f"  PROMOTION: {'YES' if promote else 'NO'}")

    # Save report
    class NE(json.JSONEncoder):
        def default(self, o):
            if isinstance(o, (np.integer,)): return int(o)
            if isinstance(o, (np.floating,)): return float(o)
            if isinstance(o, np.ndarray): return o.tolist()
            if isinstance(o, np.bool_): return bool(o)
            return super().default(o)

    report = {
        "v7_params": {"dim": best_dim, "p": bp, "q": bq, "epochs": best_ep,
                       "walk_length": best_wl, "num_walks": best_nw, "window": 10},
        "v7_mean": {v6k: round(mean[mk], 4) for mk, v6k in labels},
        "v6_baseline": V6_BASELINE,
        "seeds": seed_results,
        "promote": promote,
        "exp_winners": {"pq": f"p={bp},q={bq}", "epochs": best_ep,
                         "dim": best_dim, "walks": f"wl={best_wl},nw={best_nw}"},
    }
    rpath = os.path.join(RESULTS_DIR, "v7_fast_screen_report.json")
    with open(rpath, "w") as f:
        json.dump(report, f, indent=2, cls=NE)
    print(f"\nReport: {rpath}")

    # Save model artifact
    if promote:
        import joblib
        mpath = os.path.join(PROJECT_ROOT, "feature_engineering", "logit_model_v7_candidate.joblib")
        pairs42 = get_pairs(100000, 0.30, 42)
        feat42 = build_features_fast(emb_final, edges_df, pairs42, pop_map)
        _, fpipe = train_eval(feat42, V6_FEATURES, seed=42)
        payload = {"model": fpipe, "threshold": 0.50, "feature_names": V6_FEATURES,
                   "coef_df": None, "pu_method": "elkanoto", "n2v_params": report["v7_params"]}
        os.makedirs(os.path.dirname(mpath), exist_ok=True)
        joblib.dump(payload, mpath)
        print(f"Saved: {mpath}")

    return report


if __name__ == "__main__":
    main()
