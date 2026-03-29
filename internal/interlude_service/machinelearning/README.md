# Artist Collaboration ML Pipeline

A complete machine learning pipeline for predicting artist collaborations and shortest path distances in the artist collaboration graph.

## Overview

This pipeline converts Jupyter notebooks into production-ready Python modules with full ETL, feature engineering, and model training capabilities.

### Models

1. **Hop Predictor**: Predicts the shortest path distance (number of hops) between two artists in the collaboration graph
2. **Link Predictor**: Predicts whether a collaboration link exists between two artists

## Project Structure

```
machinelearning/
├── config/
│   ├── __init__.py
│   └── config.py              # Configuration and hyperparameters
│   └── last_fm_keys.json      # API Keys for LastFM API
├── utils/
│   ├── __init__.py
│   ├── database.py            # Database utility functions
│   └── metrics.py             # Distance and similarity metrics
├── etl/
│   ├── __init__.py
│   ├── extract_artist_edges.py      # Extract edges from database
│   ├── generate_embeddings.py       # Transform Node2Vec embeddings
│   └── load_embeddings_to_db.py     # Load embeddings back to database
│   └── last_fm_score.py             # Extract popularity and listener scores for artists
├── features/
│   ├── __init__.py
│   ├── build_features.py      # Feature engineering functions
│   ├── sampling.py            # Data sampling utilities
│   ├── pipeline_hops.py       # Hop prediction feature pipeline
│   └── pipeline_links.py      # Link prediction feature pipeline
├── models/
│   ├── __init__.py
│   ├── hop_predictor.py       # Hop prediction model
│   └── link_predictor.py      # Link prediction model
├── run_pipeline.py            # Main orchestration script
├── README.md
└── requirements.txt
```

## Installation

### Prerequisites

- Python 3.8+
- PostgreSQL database with MusicBrainz data
- Required Python packages (see requirements.txt)

### Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables (optional)
export PG_DSN="postgres://user:password@localhost:5432/musicbrainz_db"
export DATA_DIR="/path/to/data"
export OUTPUT_DIR="/path/to/output"
```

## Usage

### Running the Full Pipeline

```bash
# Run everything
python run_pipeline.py --all

# Or run with visualization
python run_pipeline.py --all --visualize
```

### Running Individual Stages

```bash
# ETL only
python run_pipeline.py --etl

# Feature engineering only
python run_pipeline.py --features

# Model training only
python run_pipeline.py --models
```

### Running Specific Steps

```bash
# Extract edges and generate embeddings
python run_pipeline.py --extract-edges --generate-embeddings

# Build features for hop prediction
python run_pipeline.py --hop-features

# Train link prediction model
python run_pipeline.py --train-link-model
```

### Customizing Parameters

```bash
# Customize link prediction sampling
python run_pipeline.py --link-features \
  --num-samples 50000 \
  --neg-ratio 0.2 \
  --random-state 42

# Train link model with custom threshold
python run_pipeline.py --train-link-model --threshold 0.7
```

## Pipeline Stages

### 1. ETL (Extract, Transform, Load)

**Extract Artist Edges**
- Queries database for artist collaboration edges
- Aggregates edge weights
- Saves to CSV

**Generate Embeddings**
- Creates artist ID → index mapping
- Converts edges to integer indices
- Trains Node2Vec embeddings using PecanPy
- Optional: Creates PCA visualization

**Load to Database**
- Inserts embeddings back into database
- Updates existing embeddings on conflict

### 2. Feature Engineering

**Hop Prediction Features**
- Loads hop count data from database
- Retrieves artist embeddings and popularity scores
- Samples k-nearest neighbors for each artist
- Builds features:
  - **Geometry**: Cosine similarity, L2 distance, dot product
  - **Popularity**: Source and destination popularity
  - **One-hop**: Neighbor-based reachability features
  - **Two-hop**: Shared neighbors, Jaccard, Adamic-Adar, preferential attachment

**Link Prediction Features**
- Creates balanced dataset with positive and negative samples
- Uses same feature engineering as hop prediction
- Supports custom negative sampling ratios

### 3. Model Training

**Hop Predictor**
- ElasticNet regression with cross-validation
- Predicts number of hops between artists
- Metrics: MAE, RMSE, Accuracy ±1 hop

**Link Predictor**
- Logistic regression with elastic net penalty
- Binary classification (link/no link)
- Metrics: ROC AUC, PR AUC, Accuracy, Precision, Recall, F1

## Feature Groups

### Geometry Features
- `cos_sim_src_dst`: Cosine similarity between embeddings
- `l2_dist_src_dst`: Euclidean distance
- `dot_src_dst`: Dot product
- `abs_diff_mean`: Mean absolute difference
- `abs_diff_max`: Max absolute difference

### Popularity Features
- `popularity_src`: Source artist popularity
- `popularity_dst`: Destination artist popularity

### One-Hop Features
- `max_cos_srcnbr_dst`: Max cosine similarity from source neighbors to destination
- `mean_cos_srcnbr_dst`: Mean cosine similarity
- `mean_topk_cos_srcnbr_dst`: Mean of top-k similarities
- `num_src_neighbors`: Number of source neighbors
- Similar features for destination → source

### Two-Hop Features
- `shared_neighbors`: Number of shared neighbors
- `jaccard_neighbors`: Jaccard coefficient
- `adamic_adar`: Adamic-Adar score
- `preferential_attachment`: Product of degrees

## Configuration

Edit `config/config.py` to customize:

- Database connection string
- File paths
- Node2Vec hyperparameters
- Model hyperparameters
- Feature groups
- Random seeds

## Model Performance

### Hop Predictor
- Predicts shortest path distance
- Best features: two-hop graph structure, neighbor aggregations, popularity

### Link Predictor
- Predicts collaboration links
- Best features: graph structure, neighbor similarities, preferential attachment

## Database Schema

### Required Tables

- `artist`: Artist metadata
- `artist_collab`: Collaboration edges
- `paths`: Shortest path hop counts
- `lastfm_artist_stats`: Popularity scores
- `artist_embeddings_n2v`: Node2Vec embeddings

## Development

### Adding New Features

1. Add feature computation to `features/build_features.py`
2. Update feature groups in `config/config.py`
3. Rebuild features using pipeline

### Adding New Models

1. Create model class in `models/`
2. Implement `fit()`, `predict()`, and `evaluate()` methods
3. Add training function
4. Update `run_pipeline.py`

## Original Notebooks

This pipeline is converted from the following notebooks in `predict_artist_hops/`:
- `embeddings.ipynb`: Node2Vec embedding generation
- `transform_pipelines.ipynb`: Feature engineering
- `models.ipynb`: Model training and evaluation
- `predict_connections.ipynb`: Link prediction
- `Extract_Transform_Audio_Features.ipynb`: Audio features (future work)

## License

See parent directory LICENSE file.

## Contact

For questions or issues, please file an issue in the repository.
