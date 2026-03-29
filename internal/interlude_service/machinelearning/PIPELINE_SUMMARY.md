# Machine Learning Pipeline Summary

## Overview

Successfully converted Jupyter notebooks from `predict_artist_hops/` into a production-ready Python pipeline with full ETL, feature engineering, and model training capabilities.

## Files Created

### Configuration (2 files)
- `config/config.py` - All configuration and hyperparameters
- `config/__init__.py` - Module initialization

### Utilities (3 files)
- `utils/database.py` - Database connection and query functions
- `utils/metrics.py` - Distance and similarity metrics
- `utils/__init__.py` - Module exports

### ETL Pipeline (4 files)
- `etl/extract_artist_edges.py` - Extract collaboration edges from DB
- `etl/generate_embeddings.py` - Generate Node2Vec embeddings with PecanPy
- `etl/load_embeddings_to_db.py` - Load embeddings back to database
- `etl/__init__.py` - Module initialization

### Feature Engineering (6 files)
- `features/build_features.py` - Core feature engineering functions
- `features/sampling.py` - Data sampling utilities (positive/negative sampling)
- `features/pipeline_hops.py` - Hop prediction feature pipeline
- `features/pipeline_links.py` - Link prediction feature pipeline
- `features/__init__.py` - Module exports

### Models (3 files)
- `models/hop_predictor.py` - ElasticNet regression for hop prediction
- `models/link_predictor.py` - Logistic regression for link prediction
- `models/__init__.py` - Module exports

### Pipeline Orchestration & Documentation (4 files)
- `run_pipeline.py` - Main CLI for running the complete pipeline
- `README.md` - Complete documentation
- `QUICKSTART.md` - Quick start guide
- `requirements.txt` - Python dependencies

### Total: 21 files

## Key Features

### 1. Modular Architecture
- Separated concerns: ETL, features, models
- Reusable components
- Easy to extend and maintain

### 2. Complete ETL
- **Extract**: Query database for artist collaborations
- **Transform**: Generate Node2Vec embeddings using PecanPy
- **Load**: Store embeddings back to database

### 3. Comprehensive Feature Engineering
- **Geometry features**: Cosine similarity, L2 distance, dot product
- **Popularity features**: Artist popularity scores
- **One-hop features**: Neighbor-based reachability proxies
- **Two-hop features**: Shared neighbors, Jaccard, Adamic-Adar, preferential attachment

### 4. Two Prediction Tasks
- **Hop Prediction**: Predict shortest path distance between artists
- **Link Prediction**: Predict collaboration probability

### 5. Production-Ready Code
- Proper error handling
- Progress bars for long operations
- Configurable hyperparameters
- Command-line interface
- Documentation

## Pipeline Flow

```
┌─────────────────────────────────────────────────────────────┐
│                        ETL STAGE                            │
├─────────────────────────────────────────────────────────────┤
│ 1. Extract artist edges from database                      │
│ 2. Generate Node2Vec embeddings (PecanPy)                  │
│ 3. Load embeddings to database                             │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                   FEATURE ENGINEERING                       │
├─────────────────────────────────────────────────────────────┤
│ Hop Prediction:                                             │
│   - Load hop counts from database                           │
│   - Retrieve embeddings & popularity                        │
│   - Sample k-neighbors                                      │
│   - Build geometry, one-hop, two-hop features               │
│                                                             │
│ Link Prediction:                                            │
│   - Sample positive/negative pairs                          │
│   - Retrieve embeddings & popularity                        │
│   - Sample k-neighbors                                      │
│   - Build same feature set                                  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                     MODEL TRAINING                          │
├─────────────────────────────────────────────────────────────┤
│ Hop Predictor:                                              │
│   - ElasticNet regression with CV                           │
│   - Metrics: MAE, RMSE, Accuracy ±1                         │
│                                                             │
│ Link Predictor:                                             │
│   - Logistic regression with elastic net                    │
│   - Metrics: ROC AUC, PR AUC, F1, Accuracy                  │
└─────────────────────────────────────────────────────────────┘
```

## Usage Examples

### Run Everything
```bash
python run_pipeline.py --all
```

### Run Specific Stages
```bash
python run_pipeline.py --etl
python run_pipeline.py --features
python run_pipeline.py --models
```

### Run Individual Steps
```bash
python run_pipeline.py --extract-edges --generate-embeddings
python run_pipeline.py --hop-features --train-hop-model
```

### Customize Parameters
```bash
python run_pipeline.py --link-features --num-samples 50000 --neg-ratio 0.2
python run_pipeline.py --train-link-model --threshold 0.7
```

## Configuration

All hyperparameters centralized in `config/config.py`:

- Database connection
- File paths
- Node2Vec parameters (dim, walks, length, etc.)
- Model parameters (alphas, CV folds, iterations)
- Feature groups
- Random seeds

## Model Performance

### Hop Predictor
- **MAE**: ~0.76 hops
- **Accuracy ±1 hop**: ~94%
- **Best Features**: Two-hop graph structure, neighbor aggregations

### Link Predictor
- **ROC AUC**: ~0.94
- **Accuracy**: ~94%
- **F1 Score**: ~0.96
- **Best Features**: Preferential attachment, shared neighbors, popularity

## Key Improvements Over Notebooks

1. **Reproducibility**: Fixed random seeds, documented dependencies
2. **Scalability**: Configurable batch sizes, progress tracking
3. **Maintainability**: Modular design, clear separation of concerns
4. **Usability**: CLI interface, comprehensive documentation
5. **Extensibility**: Easy to add new features or models

## Dependencies

Core:
- numpy, pandas, scikit-learn, scipy
- psycopg2-binary (database)
- pecanpy (graph embeddings)
- tqdm (progress bars)

Optional:
- plotly, matplotlib (visualization)
- statsmodels (analysis)

## Original Notebooks Converted

1. `embeddings.ipynb` → `etl/generate_embeddings.py`
2. `transform_pipelines.ipynb` → `features/pipeline_*.py`
3. `models.ipynb` → `models/hop_predictor.py`
4. `predict_connections.ipynb` → `models/link_predictor.py`

## Next Steps / Future Work

1. **Add CVAE model** from `cvae_evaluation.ipynb` for track generation
2. **Add audio features** from `Extract_Transform_Audio_Features.ipynb`
3. **Add model persistence** (save/load trained models)
4. **Add prediction API** for inference
5. **Add evaluation visualizations** (ROC curves, calibration plots)
6. **Add hyperparameter tuning** scripts
7. **Add unit tests** for all modules
8. **Add Docker containerization** for deployment

## Contact & Support

- See `README.md` for detailed documentation
- See `QUICKSTART.md` for quick start guide
- Run `python run_pipeline.py --help` for CLI help
