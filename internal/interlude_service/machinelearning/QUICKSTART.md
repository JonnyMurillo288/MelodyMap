# Quick Start Guide

## Installation

```bash
cd machinelearning
pip install -r requirements.txt
```

## Environment Setup

Set your database connection (optional, defaults are in config/config.py):

```bash
export PG_DSN="postgres://postgres:baseball162162@localhost:5432/musicbrainz_db?sslmode=disable"
```

## Running the Pipeline

### Option 1: Run Everything

```bash
python3 run_pipeline.py --all
```

This will:
1. Extract artist collaboration edges from the database
2. Generate Node2Vec embeddings
3. Load embeddings back to the database
4. Build features for hop prediction
5. Build features for link prediction
6. Train hop prediction model
7. Train link prediction model
8. Train CVAE model for synthetic track generation

### Option 2: Run Step by Step


```bash
# Make sure to run this in the directory you are in
export pythonPATH=$(pwd)
OR 
export pythonPATH=~/Desktop/Interlude

# Step 1: ETL
# NOTE: IF RERUNNING WITH CHANGES TO EMBEDDINGS, RUN COMMAND BELOW IN TABLE
backup_old_embeddings.sql

python3 run_pipeline.py --extract-edges
python3 run_pipeline.py --generate-embeddings
python3 run_pipeline.py --load-to-db

# Step 2: Features
python3 run_pipeline.py --hop-features
python3 run_pipeline.py --link-features

# Step 3: Models
python3 run_pipeline.py --train-hop-model
python3 run_pipeline.py --train-link-model
python3 run_pipeline.py --train-synth-tracks-model

```

### Option 3: Run Individual Modules

```bash
# ETL
cd etl
python3 extract_artist_edges.py
python3 generate_embeddings.py --visualize
python3 load_embeddings_to_db.py

# Features
cd features
python3 pipeline_hops.py
python3 pipeline_links.py --num-samples 50000 --neg-ratio 0.2

# Models
cd models
python3 hop_predictor.py
python3 link_predictor.py

# Train CVAE for synthetic track generation
python3 track_feature_predictor.py

# With custom parameters
python3 track_feature_predictor.py --epochs 50 --z-dim 32 --batch-size 256

# Skip data prep if combined embeddings already exist
python3 track_feature_predictor.py --skip-data-prep
```

## Expected Output

### ETL Stage
- `{DATA_DIR}/artist_edges.csv`: Artist collaboration edges
- `{DATA_DIR}/artist_edges.edgelist`: Integer-indexed edge list
- `{DATA_DIR}/artist_embeddings.csv`: Node2Vec embeddings
- `{DATA_DIR}/idx_to_artist.npy`: ID mapping

### Feature Stage
- `{OUTPUT_DIR}/embeddings_features.csv`: Hop prediction features (X)
- `{OUTPUT_DIR}/y_features.csv`: Hop prediction targets (y)
- `{OUTPUT_DIR}/artist_embeddings_collab_neg.csv`: Link prediction features with labels

### Model Stage
- Console output with model performance metrics
- Feature importance rankings
- Classification reports

### CVAE Model Artifacts
- `{MODEL_ENGINEERING_DIR}/features/model.pt`: PyTorch model weights
- `{MODEL_ENGINEERING_DIR}/features/prep.pkl`: Fitted preprocessor (scalers, imputers)
- `{MODEL_ENGINEERING_DIR}/features/meta.json`: Column names, hyperparameters, version info
- `{OUTPUT_DIR}/block_combined_embeddings.parquet`: Cached merged training data

## Typical Performance

### Hop Predictor
- MAE: ~0.76 hops
- Accuracy ±1 hop: ~94%

### Link Predictor
- ROC AUC: ~0.94
- Accuracy: ~94%
- F1 Score: ~0.96

### CVAE Synthetic Track Generator
Default hyperparameters (configurable in `config/config.py`):
- Latent dimension (z_dim): 16
- Hidden layers: (256, 256)
- Epochs: 30
- Batch size: 512
- Training samples: 50,000
- Validation samples: 10,000

Training logs available via TensorBoard:
```bash
tensorboard --logdir runs
```

## Common Issues

### Database Connection
```
Error: could not connect to server
```
**Solution**: Check your PG_DSN environment variable and database status

### Out of Memory
```
MemoryError during embedding generation
```
**Solution**: Reduce NODE2VEC_NUM_WALKS or NODE2VEC_WALK_LENGTH in config/config.py

### Missing Dependencies
```
ModuleNotFoundError: No module named 'pecanpy'
```
**Solution**: `pip install -r requirements.txt`

### CVAE Training Data Not Found
```
FileNotFoundError: block_track_features.parquet
```
**Solution**: Ensure track features parquet exists at `CVAE_TRACK_FEATURES_PARQUET` path, or provide a custom path:
```bash
python3 track_feature_predictor.py --track-features /path/to/your/track_features.parquet
```

### CVAE Out of GPU Memory
```
RuntimeError: CUDA out of memory
```
**Solution**: Reduce batch size or training samples:
```bash
python3 track_feature_predictor.py --batch-size 128 --train-samples 20000
```

## Next Steps

1. **Tune Hyperparameters**: Edit `config/config.py`
2. **Add Custom Features**: Modify `features/build_features.py`
3. **Experiment with Models**: Try different algorithms in `models/`
4. **Visualize Results**: Add plotting code to model evaluation

## Directory Defaults

By default, the pipeline uses:
- Data directory: `/tmp`
- Output directory: `/tmp`

To change these:
```bash
export DATA_DIR="/path/to/your/data"
export OUTPUT_DIR="/path/to/your/output"
```

Or edit them directly in `config/config.py`.

## Getting Help

```bash
python3 run_pipeline.py --help
```

Shows all available options and examples.
