'''
Test the following Models (6 files)
- `models/link_predictor.py` - Ensure the Link predictor is outputting the correct values in correct places 
- `models/return_link_embeddings.py` - Helper function to ffed into link predictor or track feature predictor
- `models/track_feature_predictor.py` - Ensure the track features predictor is outputting the correct values in correct places 
- `models/__init__.py` - Module exports
'''
import numpy as np
import pandas as pd
import pytest
import torch
import joblib
import json
import models.track_feature_predictor as m


# =========================
# Fixtures
# =========================

@pytest.fixture
def dummy_artifact(tmp_path):
    """
    Create a minimal, valid CVAE artifact on disk.
    This avoids touching your real trained model.
    """
    artifact_dir = tmp_path / "artifact"
    artifact_dir.mkdir()

    # ---- meta.json ----
    meta = {
        "c_cols": ["c1", "c2"],
        "y_cont_cols": ["f1", "f2"],
        "y_bin_cols": [],
        "z_dim": 4,
        "hidden": [8],
        "model_type": "CVAE",
        "version": "test",
    }
    (artifact_dir / "meta.json").write_text(json.dumps(meta))

    # ---- prep.pkl ----
    df = pd.DataFrame(
        {
            "c1": [1.0, 2.0, 3.0],
            "c2": [10.0, 20.0, 30.0],
            "f1": [0.1, 0.2, 0.3],
            "f2": [1.0, 1.1, 1.2],
        }
    )
    prep = m.CVAEPreprocessor().fit(
        df,
        c_cols=["c1", "c2"],
        y_cont_cols=["f1", "f2"],
        y_bin_cols=[],
    )
    joblib.dump(prep, artifact_dir / "prep.pkl")

    # ---- model.pt ----
    model = m.CVAE(
        c_dim=2,
        y_cont_dim=2,
        z_dim=4,
        hidden=(8,),
        bin_dim=0,
    )
    torch.save(model.state_dict(), artifact_dir / "model.pt")

    return artifact_dir, meta


@pytest.fixture
def dummy_prediction_df():
    """
    Mimics df_pred_links coming from:
      - get_random_prediction_links
      - get_artist_predictions
    """
    return pd.DataFrame(
        {
            "src": ["a1", "a2", "a3"],
            "dst": ["b1", "b2", "b3"],
            "c1": [1.0, 2.0, 3.0],
            "c2": [10.0, 20.0, 30.0],
        }
    )


# =========================
# 1) Artifact loading
# =========================

def test_load_cvae_artifact_contract(dummy_artifact):
    artifact_dir, meta = dummy_artifact

    model, prep, loaded_meta = m.load_cvae_artifact(str(artifact_dir), device="cpu")

    # --- structure ---
    assert isinstance(loaded_meta, dict)
    assert loaded_meta["model_type"] == "CVAE"
    assert loaded_meta["c_cols"] == meta["c_cols"]
    assert loaded_meta["y_cont_cols"] == meta["y_cont_cols"]

    # --- model ---
    assert hasattr(model, "decode")
    assert model.training is False  # model.eval() must be called

    # --- preprocessor ---
    assert prep.fitted_ is True
    assert hasattr(prep, "inverse_continuous")


# =========================
# 2) Prediction format
# =========================

def test_generate_for_rows_output_format(
    dummy_artifact,
    dummy_prediction_df,
):
    artifact_dir, meta = dummy_artifact
    model, prep, _ = m.load_cvae_artifact(str(artifact_dir), device="cpu")

    yc_samples, yb_probs = m.generate_for_rows(
        model=model,
        prep=prep,
        df_rows=dummy_prediction_df,
        c_cols=meta["c_cols"],
        n_samples=25,
        device="cpu",
    )

    # --- shapes ---
    assert yc_samples.shape == (
        len(dummy_prediction_df),
        25,
        len(meta["y_cont_cols"]),
    )

    # --- types ---
    assert isinstance(yc_samples, np.ndarray)
    assert yc_samples.dtype.kind == "f"

    # --- no binary head in this artifact ---
    assert yb_probs is None


# =========================
# 3) Final parquet output
# =========================

def test_final_parquet_output_schema(
    tmp_path,
    dummy_artifact,
    dummy_prediction_df,
):
    artifact_dir, meta = dummy_artifact
    model, prep, _ = m.load_cvae_artifact(str(artifact_dir), device="cpu")

    # ---- run prediction ----
    yc_samples, _ = m.generate_for_rows(
        model,
        prep,
        dummy_prediction_df,
        c_cols=meta["c_cols"],
        n_samples=10,
        device="cpu",
    )

    yc_mean = yc_samples.mean(axis=1)
    df_y = pd.DataFrame(yc_mean, columns=meta["y_cont_cols"])

    df_out = pd.concat(
        [
            dummy_prediction_df.reset_index(drop=True),
            df_y.reset_index(drop=True),
        ],
        axis=1,
    )

    out_path = tmp_path / "tracks.parquet"
    df_out.to_parquet(out_path)

    # ---- assertions ----
    assert out_path.exists()

    loaded = pd.read_parquet(out_path)

    # column contract
    expected_cols = (
        list(dummy_prediction_df.columns)
        + meta["y_cont_cols"]
    )
    assert list(loaded.columns) == expected_cols

    # row count preserved
    assert len(loaded) == len(dummy_prediction_df)

    # numeric sanity
    for c in meta["y_cont_cols"]:
        assert np.isfinite(loaded[c]).all()
