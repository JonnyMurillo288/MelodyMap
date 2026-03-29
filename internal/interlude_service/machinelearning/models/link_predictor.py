"""
Link prediction model training and evaluation
"""
import os
import json
import numpy as np
import pandas as pd
import joblib
from pathlib import Path
from utils import get_pg_conn
from psycopg2.extras import execute_values
from features.pipeline_links import build_link_prediction_features, build_link_prediction_embeddings_from_artist_list, genre_type_proportions_column_names
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegressionCV, LogisticRegression
from sklearn.metrics import (
    roc_auc_score,
    average_precision_score,
    log_loss,
    brier_score_loss,
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    classification_report
)

from models import artist_similarity as art_sim
from sklearn.metrics import make_scorer
from sklearn.model_selection import RandomizedSearchCV
from scipy.stats import loguniform, uniform

# Compatibility shims: pulearn 0.0.7 relies on sklearn internals that were
# removed in scikit-learn 1.3+. Patch them back before importing pulearn.
import sklearn.utils
if not hasattr(sklearn.utils, 'indices_to_mask'):
    def _indices_to_mask(indices, mask_length):
        mask = np.zeros(mask_length, dtype=bool)
        mask[indices] = True
        return mask
    sklearn.utils.indices_to_mask = _indices_to_mask

import sklearn.utils.metaestimators
if not hasattr(sklearn.utils.metaestimators, 'if_delegate_has_method'):
    def _if_delegate_has_method(delegate):
        """No-op shim: always exposes the decorated method."""
        def decorator(fn):
            return fn
        return decorator
    sklearn.utils.metaestimators.if_delegate_has_method = _if_delegate_has_method

from pulearn import ElkanotoPuClassifier, BaggingPuClassifier
from config.config import (
    FEATURE_GROUPS,
    GENRE_TYPE_CLASSIFICATION,
    LINK_PREDICTION_FEATURES,
    LOGIT_L1_RATIOS,
    LOGIT_CS_MIN,
    LOGIT_CS_MAX,
    LOGIT_CS_NUM,
    LOGIT_CV,
    LOGIT_MAX_ITER,
    LOGIT_THRESHOLD,
    TEST_SIZE,
    RANDOM_STATE,
    MODEL_ENGINEERING_DIR,
    LOGIT_NUM_PREDICTIONS,
    LOGIT_MODEL_ID,
    LOGIT_MODEL_DESC,
    LOGIT_MODEL_VERSION,
    PREDICTION_EMBEDDINGS_CSV
)


class LinkPredictor:
    """Model for predicting collaboration links between artists using PU learning"""

    def __init__(
        self,
        l1_ratios=None,
        Cs=None,
        cv=None,
        max_iter=None,
        threshold=None,
        n_jobs=4,
        random_state=None,
        pu_method="elkanoto",  # "elkanoto" or "bagging"
        hold_out_ratio=0.2,
        n_estimators=5,
        scoring="f1",
        n_iter=10,  # for RandomizedSearchCV
    ):
        if l1_ratios is None:
            l1_ratios = LOGIT_L1_RATIOS
        if Cs is None:
            Cs = np.logspace(LOGIT_CS_MIN, LOGIT_CS_MAX, LOGIT_CS_NUM)
        if cv is None:
            cv = LOGIT_CV
        if max_iter is None:
            max_iter = LOGIT_MAX_ITER
        if threshold is None:
            threshold = LOGIT_THRESHOLD
        if random_state is None:
            random_state = RANDOM_STATE

        self.threshold = threshold
        self.pu_method = pu_method
        self.n_jobs = n_jobs
        self.random_state = random_state

        # Base logistic regression
        logit = LogisticRegression(
            penalty="elasticnet",
            solver="saga",
            max_iter=max_iter,
            random_state=random_state,
        )

        # PU wrapper + param distributions
        if pu_method == "elkanoto":
            pu_clf = ElkanotoPuClassifier(
                estimator=logit,
                hold_out_ratio=hold_out_ratio,
            )
            # For elkanoto, use list values for GridSearchCV-style
            param_distributions = {
                "pu_logit__estimator__C": Cs if hasattr(Cs, '__iter__') else [Cs],
                "pu_logit__estimator__l1_ratio": l1_ratios if hasattr(l1_ratios, '__iter__') else [l1_ratios],
            }
        else:  # bagging
            pu_clf = BaggingPuClassifier(
                estimator=logit,
                n_estimators=n_estimators,
                n_jobs=n_jobs,  # use all available cores
                random_state=random_state,
            )
            # Use scipy distributions for RandomizedSearchCV
            param_distributions = {
                "pu_logit__estimator__C": loguniform(0.1, 10),
                "pu_logit__estimator__l1_ratio": uniform(0.1, 0.8),
            }  # <-- NO trailing comma here!

        # Pipeline
        pipeline = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("pu_logit", pu_clf),
        ])

        # RandomizedSearchCV for hyperparameter tuning
        self.model = RandomizedSearchCV(
            pipeline,
            param_distributions=param_distributions,
            n_iter=n_iter,
            cv=cv,
            scoring=scoring,
            n_jobs=n_jobs,
            random_state=random_state,
            refit=True,
        )

        self.feature_names = None
        self.coef_df = None

    def fit(self, X, y, feature_names=None):
        # Reset index / convert to numpy to avoid indexing issues
        if hasattr(X, 'values'):
            X = X.values
        if hasattr(y, 'values'):
            y = y.values
        
        print("Fitting the model...")
        self.model.fit(X, y)
        self.feature_names = feature_names

        if feature_names is not None:
            self._extract_coefficients(feature_names)

        return self

    def _extract_coefficients(self, feature_names):
        """Extract coefficients from the fitted PU classifier"""
        best_pipeline = self.model.best_estimator_
        pu_clf = best_pipeline.named_steps["pu_logit"]

        if self.pu_method == "elkanoto":
            coef = pu_clf.estimator.coef_.ravel()
        else:  # bagging - average across estimators
            coef = np.mean(
                [est.coef_.ravel() for est in pu_clf.estimators_],
                axis=0
            )

        self.coef_df = (
            pd.DataFrame({"feature": feature_names, "coef": coef})
            .assign(abs_coef=lambda d: d.coef.abs())
            .sort_values("abs_coef", ascending=False)
        )

    def predict_proba(self, X):
        """Predict probabilities (clamped to [0, 0.99])"""
        if hasattr(X, 'values'):
            X = X.values
        raw = self.model.predict_proba(X)
        if raw.ndim > 1 and raw.shape[1] > 1:
            raw = raw[:, 1]
        return np.clip(raw, 0.0, 0.994)

    def predict(self, X):
        """Predict binary labels"""
        proba = self.predict_proba(X)
        return (proba >= self.threshold).astype(int)

    def evaluate(self, X, y):
        if hasattr(X, 'values'):
            X = X.values
        if hasattr(y, 'values'):
            y = y.values
            
        y_prob = self.predict_proba(X)
        y_pred = self.predict(X)

        return {
            "ROC AUC": roc_auc_score(y, y_prob),
            "PR AUC": average_precision_score(y, y_prob),
            "Log Loss": log_loss(y, y_prob),
            "Brier Score": brier_score_loss(y, y_prob),
            "Accuracy": accuracy_score(y, y_pred),
            "Precision": precision_score(y, y_pred, zero_division=0),
            "Recall": recall_score(y, y_pred, zero_division=0),
            "F1 Score": f1_score(y, y_pred, zero_division=0),
        }

    def get_model_info(self):
        """Get model hyperparameters"""
        return {
            "best_params": self.model.best_params_,
            "best_score": self.model.best_score_,
            "pu_method": self.pu_method,
        }

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "model": self.model,
            "threshold": self.threshold,
            "feature_names": self.feature_names,
            "coef_df": self.coef_df,
            "pu_method": self.pu_method,
        }

        joblib.dump(payload, path)
        print(f"Saved model to {path}")

    @classmethod
    def load(cls, path):
        payload = joblib.load(path)

        obj = cls.__new__(cls)
        obj.model = payload["model"]
        obj.threshold = payload["threshold"]
        obj.feature_names = payload["feature_names"]
        obj.coef_df = payload["coef_df"]
        obj.pu_method = payload["pu_method"]

        return obj


def train_link_predictor(
    X_df,
    y,
    features=None,
    threshold=None,
    test_size=None,
    random_state=None
):
    """
    Train link prediction model

    Parameters
    ----------
    X_df : pd.DataFrame
        Features DataFrame
    y : pd.Series or array-like
        Target (binary)
    features : list, optional
        List of feature names to use. If None, uses LINK_PREDICTION_FEATURES
    threshold : float, optional
        Classification threshold
    test_size : float, optional
        Test set proportion
    random_state : int, optional
        Random seed

    Returns
    -------
    tuple
        (model, X_train, X_test, y_train, y_test)
    """
    if features is None:
        features = LINK_PREDICTION_FEATURES
    if test_size is None:
        test_size = TEST_SIZE
    if random_state is None:
        random_state = RANDOM_STATE

    # Select features
    X = X_df[features].values

    # Split data (stratified)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=test_size,
        random_state=random_state,
        stratify=y
    )

    print(f"Training set: {len(y_train)} samples")
    print(f"  Positive: {y_train.sum()}")
    print(f"  Negative: {len(y_train) - y_train.sum()}")

    print(f"Test set: {len(y_test)} samples")
    print(f"  Positive: {y_test.sum()}")
    print(f"  Negative: {len(y_test) - y_test.sum()}")

    # Train model
    print("\nTraining LogisticRegressionCV model...")
    print(f"Using features: {features}")
    model = LinkPredictor(
        pu_method="elkanoto",
        Cs=[0.1, 1, 10],
        l1_ratios=LOGIT_L1_RATIOS,
        scoring="f1",
        n_iter=10,
        cv=3,  # fewer folds = faster
    )
    model.fit(X_train, y_train, feature_names=features)
    print("Fit the model")
    # Model info
    info = model.get_model_info()
    best_params = info['best_params']
    print(f"\nBest params: {best_params}")

    # Extract with full key names
    best_C = best_params.get('pu_logit__estimator__C')
    best_l1 = best_params.get('pu_logit__estimator__l1_ratio')

    if best_C is not None:
        print(f"Best C: {best_C:.4f}")
    if best_l1 is not None:
        print(f"Best l1_ratio: {best_l1:.4f}")
    
    # Evaluate
    print("\nTraining set performance:")
    train_metrics = model.evaluate(X_train, y_train)
    for k, v in train_metrics.items():
        print(f"  {k}: {v:.4f}")

    print("\nTest set performance:")
    test_metrics = model.evaluate(X_test, y_test)
    for k, v in test_metrics.items():
        print(f"  {k}: {v:.4f}")

    # Classification report
    print("\nClassification Report (Test Set):")
    y_pred = model.predict(X_test)
    print(classification_report(y_test, y_pred, target_names=["No Link", "Link"]))

    # Feature importance
    if model.coef_df is not None:
        print("\nFeatures by absolute coefficient:")
        print(model.coef_df)

    print(model.coef_df.columns)

    return model, X_train, X_test, y_train, y_test

from features.pipeline_links import (
    build_link_prediction_features_from_input_artist
    )

def predict_link_features_from_artist(
    model,
    features,
    THRESHOLD: float,
    input_artist_id: int,
    num_candidates: int = 10000,
    random_state: int = 67,
) -> pd.DataFrame:
    """
    Build the link prediction features DataFrame for the link predictions.
    This takes in a single artist MBID and returns the link prediction features for the limit of potential connections
    OR: the context (C) used as an input to the CVAE model
    
    INPUTS:
    model: Trained Link Predictor Model
    features: List of features to use for prediction
    THRESHOLD: Float threshold for classification
    input_artist_id: str | int
        The artist MBID or int ID to predict links for
    num_candidates: int
        Number of candidate artists to consider for link prediction
    random_state: int
        Random seed for reproducibility
        
    RETURNS:
    DataFrame
        COLUMNS: src | dst | prob
            id(int) | id(int) | float
    """
        
    # Returns a DataFrame with src, dst, and features for prediction
    predicted_links = build_link_prediction_features_from_input_artist(
        input_artist_id=input_artist_id,
        num_candidates=num_candidates,
    )
    
    # Now with the predicted src-dst pairs get their embeddings features
    artist_embeddings = build_link_prediction_embeddings_from_artist_list(
        artist_list=[(row.src, row.dst) for row in predicted_links.itertuples(index=False)]
    )
    # Use the exact features the model was trained on to avoid dimension mismatch.
    # model.feature_names is set by LinkPredictor.fit() / LinkPredictor.load().
    if hasattr(model, 'feature_names') and model.feature_names is not None:
        features = list(model.feature_names)
    else:
        features = list(features)  # copy to avoid mutating the caller's global list

    X = artist_embeddings[features].values
    print(f"[DEBUG] Feature matrix shape: {X.shape}")

    probs = model.predict_proba(X)
    if probs.ndim > 1 and probs.shape[1] > 1:
        probs = probs[:, 1]  # Get probability of the positive class
    

    # Put back the src - dst pairs
    res = pd.DataFrame({
        "src": artist_embeddings["src"],
        "dst": artist_embeddings["dst"],
        "prob": probs,
    })

    # keep only edges above threshold
    return res.loc[res["prob"] >= THRESHOLD].reset_index(drop=True)


def predict_links(
    model,
    features,
    THRESHOLD = .5,
    num_negs = 1000000,
    random_state = 67,
    create = False
):
    """
    Apply the prediction's from the model
    Get ALL of the artists that SHOULD have a connection


    Parameters
    ----------
    artist_embeddings_df : pd.DataFrame
        Artist Embeddings DataFrame
    features : list, optional
        List of feature names to use. If None, uses LINK_PREDICTION_FEATURES
    threshold : float, optional
        Classification threshold
    num_negs : float, optional
        Test set proportion
    random_state : int, optional
        Random seed
    create: bool 
        If Create: create new sets of predictions
        If Not Create: Only get random set of predictions

    Returns
    -------
    Dataframe
        link_prediction_features
    """
    print("Predicting links...")
    print("Model Type:", type(model))
    
    conn = get_pg_conn()

    # TODO: Eventually we will allow the user to input their prefered input artist(s) and we can get that here 
    # So this is where the build_link_prediction_embeddings goes wrong it is creating ALL possible artist pairs
    # instead of only the ones that the user wants to predict on
    # To change this we need to change the function to take one artist and create potential links to all other artists
    # Then predict on those links only
    if create:
        X = build_link_prediction_features(num_negs,neg_ratio=1.0,random_state=random_state,save=False)
        # Only predict on non-existing pairs — scoring known links is meaningless
        artist_embeddings = X.loc[X['label'] == 0].drop(columns='label')
    
    if not create:
        preds = get_random_prediction_links(conn,num_negs)

        artist_id = [(i.src,i.dst) for i in preds.itertuples(index=False)]
        artist_embeddings = build_link_prediction_embeddings_from_artist_list(artist_list=artist_id)
    
    print(f"Final features used for prediction: {features}")
    print(f"Artist embeddings columns: {artist_embeddings.columns.tolist()}")
    print([f"Missing features: {set(features) - set(artist_embeddings.columns.tolist())}"])
    X = artist_embeddings[features].values

    probs = model.predict_proba(X)

    # Put back the src - dst pairs
    res = pd.DataFrame({
        "src": artist_embeddings["src"],
        "dst": artist_embeddings["dst"],
        "prob": probs,
    })
    conn.close()
    # keep only edges above threshold
    print("Total number of predictions:", len(res))
    print("Number of predicted links above threshold:", (res["prob"] >= THRESHOLD).sum())
    return res.loc[res["prob"] >= THRESHOLD].reset_index(drop=True)

def get_random_prediction_links(
    conn, limit: int = 50
    ) -> pd.DataFrame:
    """
    Go into the prediction_connection DB and return random prediction links
    
    :param conn: Description
    :param limit: Description
    :type limit: int
    :return: Description
    :rtype: DataFrame
    
    """
    q = f"""
        SELECT src, dst, prob
        FROM prediction_connections
        ORDER BY RANDOM()
        LIMIT {limit}
    """
    
    return pd.read_sql_query(q,conn)

def get_artist_predictions(
    artist_a: int, artist_b: int, limit: int =15
):
    """
    Given an artist (or pair of artists) get the prediciton of how likely they are to have a song together, 
    and N number of songs that they would have created together
    
    Parameters 
    ----------
    artist_a: int
        artist_id (int) for the input artist
        
    artist_b: int (optional)
        artist_id (int) for the target artist
        
    limit: (int)
        number of tracks that they would create together
    """
    return

if __name__ == "__main__":
    from config.config import ARTIST_COLLAB_NEG_CSV, LOGIT_MODEL_VERSION

    print("Loading data for training...")
    df = pd.read_csv(ARTIST_COLLAB_NEG_CSV)
    print(df.columns)
        
    gt = genre_type_proportions_column_names(GENRE_TYPE_CLASSIFICATION)
    gt = ["similarity_prop_" + i for i in gt]
    print(f"Genre Type Proportions features: {gt}")
    # LINK_PREDICTION_FEATURES.extend(gt[1:])
    # LINK_PREDICTION_FEATURES = list(set(LINK_PREDICTION_FEATURES))
    
    similarity_columns = ["artist_id"] + [i for i in genre_type_proportions_column_names(GENRE_TYPE_CLASSIFICATION)]
    temp_src = df.rename(columns={'src':'artist_id'})
    temp_dst = df.rename(columns={'dst':'artist_id'})
    a = art_sim.ArtistSimilarity(temp_src, temp_dst,GENRE_TYPE_CLASSIFICATION)
    del temp_dst,temp_src
    
    df['result'] = list(zip(df['src'], df['dst'])) # Create temporary tuple
    df['aitchison_score_genre'] = df['result'].map(a.genre_scores)
    
    FEATURE_GROUPS['genre_similarity'] = ["aitchison_score_genre"]
    LINK_PREDICTION_FEATURES.append("aitchison_score_genre")
    LINK_PREDICTION_FEATURES = list(set(LINK_PREDICTION_FEATURES))    
    
    X_df = df.drop(columns=['label', 'src', 'dst'])
    y = df['label']
    
    print(f"Data shape: X={X_df.shape}, y={y.shape}")
    print(f"Label distribution:\n{y.value_counts()}")


    model, X_train, X_test, y_train, y_test = train_link_predictor(
        X_df, y, threshold=0.5
    )
    
    # Saves the model
    output_path = os.path.join(MODEL_ENGINEERING_DIR,f"logit_model_{LOGIT_MODEL_VERSION}.joblib")
    model.save(output_path)
    
    
    
    metrics = model.evaluate(X_test, y_test)
    info = {
        "model_info": model.get_model_info(),
        "threshold": model.threshold,
        "n_features": len(model.feature_names),
        "features": model.feature_names,
        "test_metrics": metrics,
    }
    # model = LinkPredictor.load(os.path.join(MODEL_ENGINEERING_DIR,f"logit_model_{LOGIT_MODEL_VERSION}.joblib"))
    # info = {
    # "model_info": model.get_model_info(),
    # "threshold": model.threshold,
    # "n_features": len(model.feature_names),
    # "features": model.feature_names,
    # }
    
    meta_path = os.path.join(MODEL_ENGINEERING_DIR,"metadata",f"logit_model_{LOGIT_MODEL_VERSION}.json")
    # If the metadata file already exists, warn about overwriting
    if os.path.exists(meta_path):
        print(f"Warning: Overwriting existing metadata at {meta_path}")
    # If the directory does not exist, create it, and then write the metadata file
    if not os.path.exists(os.path.dirname(meta_path)):
        os.makedirs(os.path.dirname(meta_path))
    with open(meta_path, "w") as f:
        json.dump(info, f, indent=2)
    print(f"Saved metadata to {meta_path}")  
          
    # Now we will save the model predictions 
    print(f"\nGenerating link predictions for all ({LOGIT_NUM_PREDICTIONS} artists)...")
    # LINK_PREDICTION_FEATURES = [i for i in LINK_PREDICTION_FEATURES if "genre" not in i] # v5 model will not have the genre similarity, want to check the output of the model
    res = predict_links(model,LINK_PREDICTION_FEATURES,THRESHOLD=LOGIT_THRESHOLD,num_negs=LOGIT_NUM_PREDICTIONS,random_state=RANDOM_STATE,create=True)
    print("Shape of predictions:", res.shape)
    
    conn = get_pg_conn()

    rows = [
        (LOGIT_MODEL_ID, row.src, row.dst, float(row.prob))
        for row in res.itertuples(index=False)
    ]

    with conn, conn.cursor() as cur:

        # ---- insert / update model metadata ----
        cur.execute(
            """
            INSERT INTO predict_connection_model (model_id, model_date, model_desc)
            OVERRIDING SYSTEM VALUE
            VALUES (%s, NOW(), %s)
            ON CONFLICT (model_id)
            DO UPDATE SET
                model_date = EXCLUDED.model_date,
                model_desc = EXCLUDED.model_desc
            """,
            (LOGIT_MODEL_ID, LOGIT_MODEL_DESC),
        )

        # ---- bulk insert predictions ----
        execute_values(
            cur,
            """
            INSERT INTO prediction_connections (model_id, src, dst, prob)
            VALUES %s
            ON CONFLICT DO NOTHING
            """,
            rows,
        )

    conn.commit()
    conn.close()

