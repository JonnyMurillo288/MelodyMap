import json
import psycopg2
import numpy as np
import pandas as pd

from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
import umap

# ==================================================
# CONFIG
# ==================================================
EMB_PATH = "/tmp/artist_embeddings.csv"
EDGE_PATH = "/tmp/artist_edges.csv"
OUT_PATH = "acousticbrainz/static/graph.json"

MAX_EDGES = 30000
MAX_EDGES_PER_NODE = 6
N_CLUSTERS = 10
RANDOM_STATE = 42

DB_URL = "postgres://postgres:baseball162162@localhost:5432/musicbrainz_db?sslmode=disable"

# ==================================================
# 1. LOAD DATA
# ==================================================
print("Loading embeddings and edges...")

emb_df = pd.read_csv(EMB_PATH)
edges_df = pd.read_csv(
    EDGE_PATH,
    sep=r"\s+|,",
    engine="python",
    header=0
)

edges_df = edges_df[["src", "dst", "weight"]]
edges_df.columns = ["src_i", "dst_i", "weight"]

edges_df["src_i"] = edges_df["src_i"].astype(int)
edges_df["dst_i"] = edges_df["dst_i"].astype(int)
edges_df["weight"] = edges_df["weight"].astype(float)

# ==================================================
# 2. SAMPLE KNOWN EDGES
# ==================================================
edges_df = edges_df.sort_values("weight", ascending=False)

if len(edges_df) > MAX_EDGES:
    edges_df = edges_df.sample(MAX_EDGES, random_state=RANDOM_STATE)

edges_df = (
    edges_df
    .groupby("src_i", group_keys=False)
    .head(MAX_EDGES_PER_NODE)
    .reset_index(drop=True)
)

# align embeddings to sampled edges
emb_df = emb_df.loc[edges_df.index].reset_index(drop=True)

# ==================================================
# 3. EDGE → NODE EMBEDDINGS
# ==================================================
print("Aggregating edge embeddings into node embeddings...")

edge_X = emb_df.values
node_rows = []

for col in ["src_i", "dst_i"]:
    tmp = pd.DataFrame(edge_X)
    tmp["node_id"] = edges_df[col].values
    node_rows.append(tmp)

node_df = pd.concat(node_rows, ignore_index=True)

node_emb = (
    node_df
    .groupby("node_id")
    .mean()
    .reset_index()
)

# ==================================================
# 4. PCA → UMAP
# ==================================================
X = node_emb.drop(columns=["node_id"]).values
X_scaled = StandardScaler().fit_transform(X)

X_pca = PCA(
    n_components=min(20, X.shape[1]),
    random_state=RANDOM_STATE
).fit_transform(X_scaled)

X_umap = umap.UMAP(
    n_neighbors=25,
    min_dist=0.35,
    spread=1.5,
    random_state=RANDOM_STATE
).fit_transform(X_pca)

node_emb["x"] = X_umap[:, 0]
node_emb["y"] = X_umap[:, 1]

# ==================================================
# 5. CLUSTERING
# ==================================================
node_emb["cluster"] = KMeans(
    n_clusters=N_CLUSTERS,
    random_state=RANDOM_STATE
).fit_predict(X_pca)

# ==================================================
# 6. LOOKUP ARTIST NAMES
# ==================================================
print("Querying artist names from Postgres...")

conn = psycopg2.connect(DB_URL)

node_ids = node_emb["node_id"].astype(int).tolist()

sql = """
SELECT id, name
FROM artist
WHERE id = ANY(%s::int[])
"""

artist_df = pd.read_sql(
    sql,
    conn,
    params=(node_ids,)
)

conn.close()

artist_map = dict(zip(artist_df["id"], artist_df["name"]))

# ==================================================
# 7. BUILD SIGMA GRAPH JSON
# ==================================================
print("Building graph.json...")

nodes = []
for _, r in node_emb.iterrows():
    nid = int(r["node_id"])
    nodes.append({
        "key": str(nid),
        "attributes": {
            "label": artist_map.get(nid, f"Artist {nid}"),
            "x": float(r["x"]),
            "y": float(r["y"]),
            "size": 3,
            "cluster": int(r["cluster"])
        }
    })

edges = []
for i, r in edges_df.iterrows():
    edges.append({
        "key": f"e{i}",
        "source": str(int(r["src_i"])),
        "target": str(int(r["dst_i"])),
        "attributes": {
            "weight": float(r["weight"])
        }
    })

graph = {
    "nodes": nodes,
    "edges": edges
}

# ==================================================
# 8. WRITE OUTPUT
# ==================================================
with open(OUT_PATH, "w") as f:
    json.dump(graph, f)

print(f"Done. Wrote {OUT_PATH}")
