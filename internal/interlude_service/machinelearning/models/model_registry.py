"""
Model registry for plug-and-play model switching.

Does NOT modify any existing model files or training code.
Loads models lazily and caches them in memory.

Usage:
    from models.model_registry import registry

    model, version = registry.get_logit("v5")  # specific version
    model, version = registry.get_logit()       # uses DEFAULT_LOGIT_VERSION

Adding a new model:
    1. Drop logit_model_vX.joblib into feature_engineering/
    2. Add "vX": MODEL_DIR / "logit_model_vX.joblib" to LOGIT_REGISTRY
    3. Optionally set DEFAULT_LOGIT_VERSION=vX env var
"""
import os
import json
import joblib
from pathlib import Path
from threading import Lock

MODEL_DIR = Path(__file__).parent.parent / "feature_engineering"
CVAE_BASE_DIR = MODEL_DIR / "features"

# ---------------------------------------------------------------
# Registries: map version string -> file path
# To add a new model, just add a line here and drop the file in.
# ---------------------------------------------------------------
LOGIT_REGISTRY = {
    "v1": MODEL_DIR / "logit_model_v1.joblib",
    "v2": MODEL_DIR / "logit_model_v2.joblib",
    "v3": MODEL_DIR / "logit_model_v3.joblib",
    "v5": MODEL_DIR / "logit_model_v5.joblib",
    "v6": MODEL_DIR / "logit_model_v6.joblib",
    "v7": MODEL_DIR / "logit_model_v7.joblib",
}

CVAE_REGISTRY = {
    "v1": CVAE_BASE_DIR,  # contains model.pt, meta.json, prep.pkl
}

DEFAULT_LOGIT = os.getenv("DEFAULT_LOGIT_VERSION", "v7")
DEFAULT_CVAE = os.getenv("DEFAULT_CVAE_VERSION", "v1")

# Map version strings to the integer model_id stored in prediction_connections.model_id
# This bridges the registry's string versions with the DB's integer foreign key.
LOGIT_VERSION_TO_ID = {"v1": 1, "v2": 2, "v3": 3, "v5": 5, "v6": 6, "v7": 7}


class ModelCache:
    """Thread-safe lazy model loader. Models loaded once, cached for process lifetime."""

    def __init__(self):
        self._cache = {}
        self._lock = Lock()

    def get_logit(self, version: str = None):
        """Load and return (model, version_string) for a logit model."""
        version = version or DEFAULT_LOGIT
        # Strip common prefixes so callers can pass "logit_v5" or just "v5"
        version = version.replace("logit_", "")
        key = f"logit_{version}"

        if key not in self._cache:
            with self._lock:
                if key not in self._cache:
                    path = LOGIT_REGISTRY.get(version)
                    if not path or not path.exists():
                        available = [v for v, p in LOGIT_REGISTRY.items() if p.exists()]
                        raise ValueError(
                            f"Logit model version '{version}' not found. "
                            f"Available: {available}"
                        )
                    try:
                        from models.link_predictor import LinkPredictor
                        self._cache[key] = LinkPredictor.load(path)
                    except (KeyError, TypeError):
                        # Older model versions may be raw sklearn objects
                        # (not wrapped in LinkPredictor.save format)
                        raw = joblib.load(path)
                        if hasattr(raw, "predict_proba"):
                            self._cache[key] = raw
                        elif isinstance(raw, dict):
                            # Try to extract the sklearn model from whatever keys exist
                            for k, v in raw.items():
                                if hasattr(v, "predict_proba"):
                                    self._cache[key] = v
                                    break
                            else:
                                raise ValueError(
                                    f"Model file '{path}' has unrecognized format. "
                                    f"Keys: {list(raw.keys())}"
                                )
                        else:
                            raise ValueError(f"Model file '{path}' has unrecognized format: {type(raw)}")
                        print(f"[model_registry] Loaded '{version}' as raw sklearn model (legacy format)")
        return self._cache[key], version

    def get_cvae(self, version: str = None):
        """Load and return ((model, prep, meta), version_string) for a CVAE model."""
        version = version or DEFAULT_CVAE
        version = version.replace("cvae_", "")
        key = f"cvae_{version}"

        if key not in self._cache:
            with self._lock:
                if key not in self._cache:
                    path = CVAE_REGISTRY.get(version)
                    if not path or not path.exists():
                        available = [v for v, p in CVAE_REGISTRY.items() if p.exists()]
                        raise ValueError(
                            f"CVAE version '{version}' not found. "
                            f"Available: {available}"
                        )
                    from models.track_feature_predictor import load_cvae_artifact
                    model, prep, meta = load_cvae_artifact(str(path))
                    self._cache[key] = (model, prep, meta)
        return self._cache[key], version

    def list_available(self) -> dict:
        """Return available model versions and current defaults."""
        logit_available = {v: str(p) for v, p in LOGIT_REGISTRY.items() if p.exists()}
        cvae_available = {v: str(p) for v, p in CVAE_REGISTRY.items() if p.exists()}

        loaded = [k for k in self._cache.keys()]

        return {
            "logit": {
                "available": list(logit_available.keys()),
                "default": DEFAULT_LOGIT,
            },
            "cvae": {
                "available": list(cvae_available.keys()),
                "default": DEFAULT_CVAE,
            },
            "currently_loaded": loaded,
        }

    def preload_defaults(self):
        """Eagerly load default models on startup. Non-blocking if files missing."""
        try:
            self.get_logit()
        except (ValueError, FileNotFoundError) as e:
            print(f"[model_registry] Warning: could not preload default logit: {e}")
        try:
            self.get_cvae()
        except (ValueError, FileNotFoundError) as e:
            print(f"[model_registry] Warning: could not preload default CVAE: {e}")


# Singleton
registry = ModelCache()
