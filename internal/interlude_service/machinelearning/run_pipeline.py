#!/usr/bin/env python
"""
Main pipeline orchestration script

This script runs the full ML pipeline:
1. ETL: Extract artist edges, generate embeddings, load to DB
2. Features: Build features for hop prediction and link prediction
3. Models: Train and evaluate both models
"""
import argparse
import sys
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))


def run_etl(args):
    """Run ETL pipeline"""
    print("\n" + "=" * 80)
    print("STEP 1: ETL PIPELINE")
    print("=" * 80)

    if args.extract_edges:
        print("\n--- Extracting artist edges ---")
        from etl.extract_artist_edges import extract_artist_edges
        extract_artist_edges()

    if args.generate_embeddings:
        print("\n--- Generating embeddings ---")
        from etl.generate_embeddings import generate_embeddings
        generate_embeddings(visualize=args.visualize)

    if args.load_to_db:
        print("\n--- Loading embeddings to database ---")
        from etl.load_embeddings_to_db import load_embeddings_to_db
        load_embeddings_to_db()


def run_features(args):
    """Run feature engineering pipeline"""
    print("\n" + "=" * 80)
    print("STEP 2: FEATURE ENGINEERING")
    print("=" * 80)

    if args.hop_features:
        print("\n--- Building hop prediction features ---")
        from features.pipeline_hops import build_hop_prediction_features
        build_hop_prediction_features()

    if args.link_features:
        print("\n--- Building link prediction features ---")
        from features.pipeline_links import build_link_prediction_features
        build_link_prediction_features(
            num_true_samples=args.num_samples,
            neg_ratio=args.neg_ratio,
            random_state=args.random_state
        )


def run_models(args):
    """Run model training pipeline"""
    print("\n" + "=" * 80)
    print("STEP 3: MODEL TRAINING")
    print("=" * 80)

    if args.train_hop_model:
        print("\n--- Training hop prediction model ---")
        from models.hop_predictor import train_hop_predictor
        from config.config import EMBEDDINGS_FEATURES_CSV, Y_FEATURES_CSV
        import pandas as pd

        X_df = pd.read_csv(EMBEDDINGS_FEATURES_CSV)
        y = pd.read_csv(Y_FEATURES_CSV).squeeze()
        train_hop_predictor(X_df, y)

    if args.train_link_model:
        print("\n--- Training link prediction model ---")
        from models.link_predictor import train_link_predictor
        from config.config import ARTIST_COLLAB_NEG_CSV
        import pandas as pd

        df = pd.read_csv(ARTIST_COLLAB_NEG_CSV)
        X_df = df.drop(columns=['label', 'src', 'dst'])
        y = df['label']
        train_link_predictor(X_df, y, threshold=args.threshold)
    
    if args.train_synth_tracks_model:
        print("\n--- Training CVAE for synthetic tracks ---")
        from models.track_feature_predictor import train_cvae_synth_tracks

        train_cvae_synth_tracks(
            train_sample_size=args.num_samples if args.num_samples != 10000 else None,
            seed=args.random_state,
        )


def main():
    parser = argparse.ArgumentParser(
        description="Run the complete ML pipeline for artist collaboration prediction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
        Examples:
        # Run full pipeline
        python run_pipeline.py --all

        # Run only ETL
        python run_pipeline.py --etl

        # Run only feature engineering
        python run_pipeline.py --features

        # Run only model training
        python run_pipeline.py --models

        # Run specific steps
        python run_pipeline.py --extract-edges --generate-embeddings
        python run_pipeline.py --hop-features --train-hop-model

        # Customize link prediction sampling
        python run_pipeline.py --link-features --num-samples 50000 --neg-ratio 0.2
        
        # Applying the model
        python track_feature_predictor.py --manual-or-random True --src-artist 129834 --dest-artist -1 --num-samples 15
        """
    )

    # Main pipeline flags
    parser.add_argument("--all", action="store_true",
                       help="Run complete pipeline (ETL + Features + Models)")
    parser.add_argument("--etl", action="store_true",
                       help="Run ETL pipeline")
    parser.add_argument("--features", action="store_true",
                       help="Run feature engineering pipeline")
    parser.add_argument("--models", action="store_true",
                       help="Run model training pipeline")
    parser.add_argument("--application",action="store_true",
                        help="Run application of model link prediction + predicted tracks")

    # ETL step flags
    etl_group = parser.add_argument_group("ETL Steps")
    etl_group.add_argument("--extract-edges", action="store_true",
                          help="Extract artist collaboration edges from database")
    etl_group.add_argument("--generate-embeddings", action="store_true",
                          help="Generate Node2Vec embeddings")
    etl_group.add_argument("--load-to-db", action="store_true",
                          help="Load embeddings back to database")
    etl_group.add_argument("--visualize", action="store_true",
                          help="Create embedding visualization (with --generate-embeddings)")

    # Feature engineering flags
    feat_group = parser.add_argument_group("Feature Engineering Steps")
    feat_group.add_argument("--hop-features", action="store_true",
                           help="Build hop prediction features")
    feat_group.add_argument("--link-features", action="store_true",
                           help="Build link prediction features")

    # Model training flags
    model_group = parser.add_argument_group("Model Training Steps")
    model_group.add_argument("--train-hop-model", action="store_true",
                            help="Train hop prediction model")
    model_group.add_argument("--train-link-model", action="store_true",
                            help="Train link prediction model")
    model_group.add_argument('--train-synth-tracks-model', action="store_true",
                            help="Train the CVAE NN for synth tracks")

    # Model application flags
    application_group = parser.add_argument_group("Model Prediction Application Loader")
    application_group.add_argument("--predict-links", action="store_true",
                            help="Predict Just Links from the model")
    application_group.add_argument("--predict-tracks", action="store_true",
                            help="Predict Just Track from the model: Must provide links")
    application_group.add_argument("--predict-full", action="store_true",
                            help="Predict both Links & Tracks from the model")

    # Hyperparameters
    param_group = parser.add_argument_group("Parameters")
    param_group.add_argument("--num-samples", type=int, default=10000,
                            help="Number of positive samples for link prediction (default: 10000)")
    param_group.add_argument("--neg-ratio", type=float, default=0.15,
                            help="Negative to positive ratio for link prediction (default: 0.15)")
    param_group.add_argument("--threshold", type=float, default=0.5,
                            help="Classification threshold for link prediction (default: 0.5)")
    param_group.add_argument("--random-state", type=int, default=42,
                            help="Random seed (default: 42)")
    
    # For the Model-Predictions
    param_group.add_argument("--manual-or-random", type=bool,default=False,
                        help="Are you inputing artists or should we return random artists?")
    param_group.add_argument("--src-artist", type=int, default=-1,
                       help="Number of positive samples")
    param_group.add_argument("--dest-artist", type=int, default=-1,
                       help="Ratio of negative to positive samples")


    args = parser.parse_args()

    # Handle --all flag
    if args.all:
        args.etl = True
        args.features = True
        args.models = True

    # Handle pipeline-level flags
    if args.etl:
        args.extract_edges = True
        args.generate_embeddings = True
        args.load_to_db = True

    if args.features:
        args.hop_features = True
        args.link_features = True

    if args.models:
        args.train_hop_model = True
        args.train_link_model = True
        args.train_synth_tracks_model = True

    # Check if any action is specified
    if not any([
        args.extract_edges, args.generate_embeddings, args.load_to_db,
        args.hop_features, args.link_features,
        args.train_hop_model, args.train_link_model, args.train_synth_tracks_model
    ]):
        parser.print_help()
        sys.exit(1)

    # Run pipelines
    try:
        if any([args.extract_edges, args.generate_embeddings, args.load_to_db]):
            run_etl(args)

        if any([args.hop_features, args.link_features]):
            run_features(args)

        if any([args.train_hop_model, args.train_link_model, args.train_synth_tracks_model]):
            run_models(args)
            
        print("\n" + "=" * 80)
        print("PIPELINE COMPLETED SUCCESSFULLY")
        print("=" * 80)

    except Exception as e:
        print(f"\n!!! ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
