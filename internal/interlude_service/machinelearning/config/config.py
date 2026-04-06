"""
Configuration file for the machine learning pipeline
"""
import os
import time

# Database Configuration
_raw_dsn = os.getenv(
    "PG_DSN",
    "postgres://postgres:baseball162162@localhost:5432/musicbrainz_db?sslmode=disable"
)
# Ensure search_path includes musicbrainz schema so queries work without schema prefix.
# On Render, the default search_path is 'public' only.
if "options=" not in _raw_dsn:
    _sep = "&" if "?" in _raw_dsn else "?"
    DB_URL = _raw_dsn + _sep + "options=-csearch_path%3Dmusicbrainz,public"
else:
    DB_URL = _raw_dsn

# Keys to the LastFM API
LAST_FM_KEYS = {
    "Application name": "Melody-Map",
    "api_key": os.environ.get("LASTFM_API_KEY", ""),
    "secret": os.environ.get("LASTFM_API_SECRET", ""),
    "Registered to": "Jonathan_m98",
}

# Spotify API (Client Credentials for batch ETL)
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

# Internal service-to-service auth
INTERNAL_SERVICE_SECRET = os.environ.get("INTERNAL_SERVICE_SECRET", "")
SPOTIFY_SIMILARITY_THRESHOLD = 0.8

# File Paths
DATA_DIR = os.getenv("DATA_DIR", "/tmp")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/tmp")
MODEL_RESULTS_DIR = os.getenv("MODEL_RESUTS_DIR",'./output')
MODEL_ENGINEERING_DIR = os.getenv("MODEL_ENGINEERING_DIR","./feature_engineering")
TRAINING_DATA_DIR = os.getenv("TRAINING_DATA_DIR", "training_data")

# ETL Paths
ARTIST_EDGES_CSV = os.path.join(DATA_DIR, "artist_edges.csv")
ARTIST_EDGES_EDGELIST = os.path.join(DATA_DIR, "artist_edges.edgelist")
ARTIST_EMBEDDINGS_CSV = os.path.join(DATA_DIR, "artist_embeddings.csv")
IDX_TO_ARTIST_NPY = os.path.join(DATA_DIR, "idx_to_artist.npy")

# Feature Engineering Paths
EMBEDDINGS_FEATURES_CSV = os.path.join(OUTPUT_DIR, "embeddings_features.csv")
Y_FEATURES_CSV = os.path.join(OUTPUT_DIR, "y_features.csv")
ARTIST_COLLAB_NEG_CSV = os.path.join(OUTPUT_DIR, "artist_embeddings_collab_neg.csv")
ARTIST_COLLAB_ONLY_NEG_CSV = os.path.join(OUTPUT_DIR, "artist_embeddings_only_neg_{}.csv")
# training data, allowing for one time training sets that dont have to be regenerated
# Super slow to run, thats why saving persistent and not temp rn
# Training Dataset
BLOCK_TRACK_AUDIO_FEATURES_PARQUET = os.path.join(TRAINING_DATA_DIR, 'cvae_training/block_track_features.parquet')

# Prediction Output Paths
PREDICTION_EMBEDDINGS_CSV = os.path.join(MODEL_RESULTS_DIR,"prediction_embeddings.csv")
TRACK_FEATURES_PARQUET = os.path.join(MODEL_RESULTS_DIR,"predictions_track_features.parquet")

# CVAE MODEL PATHS
CVAE_ARTIFACT_PATH = os.path.join(MODEL_ENGINEERING_DIR, "features")
CVAE_TRACK_FEATURES_PARQUET = os.path.join(OUTPUT_DIR, "block_track_features.parquet")
CVAE_COMBINED_EMBEDDINGS_PARQUET = os.path.join(OUTPUT_DIR, "block_combined_embeddings.parquet")

# CVAE Training Parameters
CVAE_Z_DIM = 16
CVAE_HIDDEN = (256, 256)
CVAE_DROPOUT = 0.1
CVAE_BATCH_SIZE = 512
CVAE_EPOCHS = 30
CVAE_LR = 1e-3
CVAE_WARMUP_EPOCHS = 10
CVAE_MAX_BETA = 1.0
CVAE_TRAIN_SAMPLE_SIZE = 50_000
CVAE_VAL_SAMPLE_SIZE = 10_000


# Model Configuration
RANDOM_STATE = 42
TEST_SIZE = 0.2
VALIDATION_SIZE = 0.15

# Node2Vec Parameters
NODE2VEC_DIM = 128
NODE2VEC_NUM_WALKS = 20
NODE2VEC_WALK_LENGTH = 20
NODE2VEC_WINDOW_SIZE = 10
NODE2VEC_EPOCHS = 1
NODE2VEC_P = 1.0
NODE2VEC_Q = 0.5
NODE2VEC_WORKERS = 2

# Genre Type Classification for similarity features
GENRE_TYPE_CLASSIFICATION = 'rosamerica'

# Feature Groups
FEATURE_GROUPS = {
    "geometry": [
        "cos_sim_src_dst",
        "l2_dist_src_dst",
        "dot_src_dst",
        "abs_diff_mean",
        "abs_diff_max",
    ],
    "popularity": [
        "popularity_src",
        "popularity_dst",
    ],
    "popularity_interactions": [
        "popularity_ratio",
        "popularity_diff",
        "popularity_product",
        "log_popularity_ratio",
    ],
    "one_hop": [
        "max_cos_srcnbr_dst",
        "mean_cos_srcnbr_dst",
        "mean_topk_cos_srcnbr_dst",
        "num_src_neighbors",
        "max_cos_dstnbr_src",
        "mean_cos_dstnbr_src",
        "mean_topk_cos_dstnbr_src",
        "num_dst_neighbors",
    ],
    "two_hop": [
        "shared_neighbors",
        "jaccard_neighbors",
        "adamic_adar",
        "preferential_attachment",
    ],
    "genre_similarity": [
        # Genre similarity features will be added here dynamically
    ]
}

# Selected features for final predict number of hops model
FINAL_FEATURES = [
    # popularity
    "popularity_src",
    "popularity_dst",
    # one-hop
    "num_src_neighbors",
    "num_dst_neighbors",
    "max_cos_srcnbr_dst",
    "max_cos_dstnbr_src",
    "mean_topk_cos_srcnbr_dst",
    "mean_topk_cos_dstnbr_src",
    # two-hop
    "shared_neighbors",
    "jaccard_neighbors",
    "adamic_adar",
    "preferential_attachment",
]

# Link Prediction Features
LINK_PREDICTION_FEATURES = [
    'cos_sim_src_dst',
    'dot_src_dst',
    'l2_dist_src_dst',
    'popularity_dst',
    'popularity_src',
    'num_dst_neighbors',
    'max_cos_srcnbr_dst',
    'mean_topk_cos_dstnbr_src',
    'preferential_attachment',
    'adamic_adar',
    'jaccard_neighbors',
    # v6 popularity interaction features
    'popularity_ratio',
    'popularity_diff',
    'popularity_product',
    'log_popularity_ratio',
]

# LOGIT Model Version - If changing below or training new, update this to new version
LOGIT_MODEL_VERSION = "v6"
LOGIT_MODEL_ID = 6
LOGIT_MODEL_DESC = """
Logistic Regression with PUSCAR with the following X variables:
TO_USE = {
    "geometry": ["cos_sim_src_dst","dot_src_dst","l2_dist_src_dst"],
    "popularity": ["popularity_dst","popularity_src"],
    "one_hop": ["num_dst_neighbors","max_cos_srcnbr_dst","mean_topk_cos_dstnbr_src"],
    "two_hop": ["preferential_attachment","adamic_adar","jaccard_neighbors"],
    "genre_similarity: ['aitchison_score_genre'],
        "genre_similarity": ['similarity_prop_genre_rosamerica_dan',
       'similarity_prop_genre_rosamerica_hip',
       'similarity_prop_genre_rosamerica_jaz',
       'similarity_prop_genre_rosamerica_pop',
       'similarity_prop_genre_rosamerica_rhy',
       'similarity_prop_genre_rosamerica_roc',
       'similarity_prop_genre_rosamerica_spe']
}
"""

LOGIT_NUM_PREDICTIONS = 4_000_000

# Model Parameters
ELASTIC_NET_L1_RATIOS = [0.3, 0.5, 0.7, 0.9, 1.0]
ELASTIC_NET_ALPHAS_MIN = -4
ELASTIC_NET_ALPHAS_MAX = 1
ELASTIC_NET_ALPHAS_NUM = 50
ELASTIC_NET_CV = 5
ELASTIC_NET_MAX_ITER = 20000

# Logistic Regression Parameters
LOGIT_L1_RATIOS = [0.5, 0.8, 1.0]
LOGIT_CS_MIN = 0.1
LOGIT_CS_MAX = 1
LOGIT_CS_NUM = 10
LOGIT_CV = 10
LOGIT_MAX_ITER = 3000
LOGIT_THRESHOLD = 0.75
