"""
Hop prediction model training and evaluation
"""
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import ElasticNetCV
from sklearn.metrics import mean_absolute_error, mean_squared_error

from config.config import (
    FINAL_FEATURES,
    ELASTIC_NET_L1_RATIOS,
    ELASTIC_NET_ALPHAS_MIN,
    ELASTIC_NET_ALPHAS_MAX,
    ELASTIC_NET_ALPHAS_NUM,
    ELASTIC_NET_CV,
    ELASTIC_NET_MAX_ITER,
    TEST_SIZE,
    RANDOM_STATE
)


class HopPredictor:
    """Model for predicting number of hops between artists"""

    def __init__(
        self,
        l1_ratios=None,
        alphas=None,
        cv=None,
        max_iter=None,
        n_jobs=-1
    ):
        """
        Initialize hop predictor

        Parameters
        ----------
        l1_ratios : list, optional
            L1 ratios for elastic net
        alphas : array-like, optional
            Alpha values to try
        cv : int, optional
            Number of cross-validation folds
        max_iter : int, optional
            Maximum number of iterations
        n_jobs : int
            Number of parallel jobs
        """
        if l1_ratios is None:
            l1_ratios = ELASTIC_NET_L1_RATIOS
        if alphas is None:
            alphas = np.logspace(
                ELASTIC_NET_ALPHAS_MIN,
                ELASTIC_NET_ALPHAS_MAX,
                ELASTIC_NET_ALPHAS_NUM
            )
        if cv is None:
            cv = ELASTIC_NET_CV
        if max_iter is None:
            max_iter = ELASTIC_NET_MAX_ITER

        self.pipeline = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("enet", ElasticNetCV(
                l1_ratio=l1_ratios,
                alphas=alphas,
                cv=cv,
                max_iter=max_iter,
                n_jobs=n_jobs
            ))
        ])

        self.feature_names = None
        self.coef_df = None

    def fit(self, X, y, feature_names=None):
        """
        Fit the model

        Parameters
        ----------
        X : array-like
            Features
        y : array-like
            Target
        feature_names : list, optional
            Feature names

        Returns
        -------
        self
        """
        self.pipeline.fit(X, y)
        self.feature_names = feature_names

        if feature_names is not None:
            enet = self.pipeline.named_steps["enet"]
            self.coef_df = (
                pd.DataFrame({
                    "feature": feature_names,
                    "coef": enet.coef_
                })
                .assign(abs_coef=lambda d: d.coef.abs())
                .sort_values("abs_coef", ascending=False)
            )

        return self

    def predict(self, X):
        """Predict hop counts"""
        return self.pipeline.predict(X)

    def evaluate(self, X, y):
        """
        Evaluate model performance

        Parameters
        ----------
        X : array-like
            Features
        y : array-like
            True target

        Returns
        -------
        dict
            Dictionary of metrics
        """
        y_pred = self.predict(X)

        mae = mean_absolute_error(y, y_pred)
        rmse = mean_squared_error(y, y_pred, squared=False)
        acc_pm1 = np.mean(np.abs(np.round(y_pred) - y) <= 1)

        return {
            "MAE": mae,
            "RMSE": rmse,
            "Accuracy ±1 hop": acc_pm1
        }

    def get_model_info(self):
        """Get model hyperparameters"""
        enet = self.pipeline.named_steps["enet"]
        return {
            "alpha": enet.alpha_,
            "l1_ratio": enet.l1_ratio_
        }


def train_hop_predictor(X_df, y, features=None, test_size=None, random_state=None):
    """
    Train hop prediction model

    Parameters
    ----------
    X_df : pd.DataFrame
        Features DataFrame
    y : pd.Series or array-like
        Target
    features : list, optional
        List of feature names to use. If None, uses FINAL_FEATURES
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
        features = FINAL_FEATURES
    if test_size is None:
        test_size = TEST_SIZE
    if random_state is None:
        random_state = RANDOM_STATE

    # Select features
    X = X_df[features].values

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=test_size,
        random_state=random_state
    )

    # Train model
    print("Training ElasticNet model...")
    model = HopPredictor()
    model.fit(X_train, y_train, feature_names=features)

    # Model info
    info = model.get_model_info()
    print(f"Best alpha: {info['alpha']:.4f}")
    print(f"Best l1_ratio: {info['l1_ratio']:.4f}")

    # Evaluate
    print("\nTraining set performance:")
    train_metrics = model.evaluate(X_train, y_train)
    for k, v in train_metrics.items():
        print(f"  {k}: {v:.4f}")

    print("\nTest set performance:")
    test_metrics = model.evaluate(X_test, y_test)
    for k, v in test_metrics.items():
        print(f"  {k}: {v:.4f}")

    # Feature importance
    if model.coef_df is not None:
        print("\nTop 10 features by absolute coefficient:")
        print(model.coef_df.head(10))

    return model, X_train, X_test, y_train, y_test


if __name__ == "__main__":
    from config.config import EMBEDDINGS_FEATURES_CSV, Y_FEATURES_CSV

    print("Loading data...")
    X_df = pd.read_csv(EMBEDDINGS_FEATURES_CSV)
    y = pd.read_csv(Y_FEATURES_CSV).squeeze()

    print(f"Data shape: X={X_df.shape}, y={y.shape}")

    model, X_train, X_test, y_train, y_test = train_hop_predictor(X_df, y)
