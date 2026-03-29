"""
Tests for models/track_similarity.py

Covers:
- aitchison distance (pure math, no DB)
- _validate_vector / _validate_aitchison helpers
- TrackSimilarity.sort_similarity_scores (pure logic)
- TrackSimilarity.calculate_aitchson_scores_for_tracks (pure logic with mock DataFrames)
- TrackSimilarity.__init__ / extract_features (DB calls mocked)
"""
import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from scipy.spatial.distance import norm

from models.track_similarity import (
    aitchison,
    _validate_vector,
    _validate_aitchison,
    TrackSimilarity,
)
from config.config import GENRE_TYPE_CLASSIFICATION
from features.pipeline_links import genre_type_proportions_column_names


# ============================
# Helpers
# ============================

GENRE_COLS = genre_type_proportions_column_names(GENRE_TYPE_CLASSIFICATION)
# e.g. ['genre_rosamerica_cla', ..., 'genre_rosamerica_spe']


def _make_synth_df(n_rows=1):
    """Build a minimal synthetic_features DataFrame with genre columns + synthetic_track_id.
    Uses integer IDs to match the database schema (avoids object-dtype from mixed str/float rows).
    """
    rng = np.random.default_rng(42)
    data = {}
    for col in GENRE_COLS:
        data[col] = rng.uniform(0.01, 1.0, size=n_rows).astype(np.float64)
    df = pd.DataFrame(data)
    df.insert(0, "synthetic_track_id", list(range(1000, 1000 + n_rows)))
    return df


def _make_neighbor_df(n_rows=5):
    """Build a minimal neighbor_features DataFrame with genre columns + track_id.
    Uses integer IDs to match the database schema.
    """
    rng = np.random.default_rng(99)
    data = {}
    for col in GENRE_COLS:
        data[col] = rng.uniform(0.01, 1.0, size=n_rows).astype(np.float64)
    df = pd.DataFrame(data)
    df.insert(0, "track_id", list(range(2000, 2000 + n_rows)))
    return df


# ============================
# 1) _validate_vector
# ============================

class TestValidateVector:
    def test_1d_array_passthrough(self):
        v = np.array([1.0, 2.0, 3.0])
        result = _validate_vector(v)
        np.testing.assert_array_equal(result, v)

    def test_list_converted_to_array(self):
        result = _validate_vector([4.0, 5.0])
        assert isinstance(result, np.ndarray)
        assert result.ndim == 1

    def test_2d_array_raises(self):
        with pytest.raises(ValueError, match="1-D"):
            _validate_vector(np.array([[1, 2], [3, 4]]))

    def test_scalar_raises(self):
        # scalar becomes 0-d array
        with pytest.raises(ValueError, match="1-D"):
            _validate_vector(np.array(5))


# ============================
# 2) _validate_aitchison
# ============================

class TestValidateAitchison:
    def test_positive_values_pass(self):
        w = np.array([0.1, 0.5, 1.0])
        result = _validate_aitchison(w, "u")
        np.testing.assert_array_equal(result, w)

    def test_zero_value_raises(self):
        with pytest.raises(ValueError, match="positive"):
            _validate_aitchison(np.array([0.0, 0.5]), "u")

    def test_negative_value_raises(self):
        with pytest.raises(ValueError, match="positive"):
            _validate_aitchison(np.array([-1.0, 0.5]), "v")


# ============================
# 3) aitchison distance
# ============================

class TestAitchisonDistance:
    def test_identical_vectors_distance_zero(self):
        u = np.array([0.3, 0.5, 0.2])
        assert aitchison(u, u) == pytest.approx(0.0, abs=1e-12)

    def test_symmetric(self):
        u = np.array([0.1, 0.4, 0.5])
        v = np.array([0.3, 0.3, 0.4])
        assert aitchison(u, v) == pytest.approx(aitchison(v, u), abs=1e-12)

    def test_known_value(self):
        """Manually compute expected Aitchison distance for a simple case."""
        u = np.array([1.0, 2.0])
        v = np.array([2.0, 1.0])
        log_ratio = np.log(u / v)  # [ln(0.5), ln(2)]
        centered = log_ratio - np.mean(log_ratio)
        expected = norm(centered)
        assert aitchison(u, v) == pytest.approx(expected, abs=1e-12)

    def test_positive_distance_for_different_vectors(self):
        u = np.array([0.2, 0.3, 0.5])
        v = np.array([0.5, 0.3, 0.2])
        assert aitchison(u, v) > 0

    def test_scale_invariance(self):
        """Aitchison distance is scale-invariant: d(u, v) == d(k*u, k*v)."""
        u = np.array([1.0, 2.0, 3.0])
        v = np.array([3.0, 2.0, 1.0])
        k = 5.0
        assert aitchison(u, v) == pytest.approx(aitchison(k * u, k * v), abs=1e-12)

    def test_zero_in_u_raises(self):
        with pytest.raises(ValueError):
            aitchison(np.array([0.0, 0.5]), np.array([0.5, 0.5]))

    def test_zero_in_v_raises(self):
        with pytest.raises(ValueError):
            aitchison(np.array([0.5, 0.5]), np.array([0.0, 0.5]))

    def test_2d_input_raises(self):
        with pytest.raises(ValueError):
            aitchison(np.array([[1, 2]]), np.array([1, 2]))


# ============================
# 4) sort_similarity_scores
# ============================

class TestSortSimilarityScores:
    @pytest.fixture
    def ts_instance(self):
        """Create a TrackSimilarity without running __init__ logic (skip DB)."""
        obj = object.__new__(TrackSimilarity)
        return obj

    def test_ascending_sort(self, ts_instance):
        scores = {
            "synth_0": [("t1", 5.0), ("t2", 1.0), ("t3", 3.0)],
        }
        result = ts_instance.sort_similarity_scores(scores, method="ascending")
        ids = [t[0] for t in result["synth_0"]]
        vals = [t[1] for t in result["synth_0"]]
        assert ids == ["t2", "t3", "t1"]
        assert vals == sorted(vals)

    def test_empty_scores(self, ts_instance):
        result = ts_instance.sort_similarity_scores({})
        assert result == {}

    def test_single_entry(self, ts_instance):
        scores = {"s1": [("t1", 2.0)]}
        result = ts_instance.sort_similarity_scores(scores)
        assert result == {"s1": [("t1", 2.0)]}

    def test_multiple_synth_tracks(self, ts_instance):
        scores = {
            "s1": [("t1", 3.0), ("t2", 1.0)],
            "s2": [("t3", 9.0), ("t4", 2.0), ("t5", 5.0)],
        }
        result = ts_instance.sort_similarity_scores(scores)
        assert [t[0] for t in result["s1"]] == ["t2", "t1"]
        assert [t[0] for t in result["s2"]] == ["t4", "t5", "t3"]

    def test_ties_preserved(self, ts_instance):
        scores = {"s1": [("t1", 2.0), ("t2", 2.0), ("t3", 1.0)]}
        result = ts_instance.sort_similarity_scores(scores)
        assert result["s1"][0] == ("t3", 1.0)
        # Both t1 and t2 have score 2.0, order among ties is stable (insertion order)
        assert result["s1"][1][1] == 2.0
        assert result["s1"][2][1] == 2.0


# ============================
# 5) calculate_aitchson_scores_for_tracks
# ============================

class TestCalculateAitchsonScores:
    @pytest.fixture
    def ts_instance(self):
        obj = object.__new__(TrackSimilarity)
        return obj

    def test_returns_dict_with_synth_keys(self, ts_instance):
        synth_df = _make_synth_df(2)
        neighbor_df = _make_neighbor_df(3)
        result = ts_instance.calculate_aitchson_scores_for_tracks(synth_df, neighbor_df)

        assert isinstance(result, dict)
        assert set(result.keys()) == {1000, 1001}

    def test_each_synth_has_scores_for_all_neighbors(self, ts_instance):
        synth_df = _make_synth_df(1)
        neighbor_df = _make_neighbor_df(4)
        result = ts_instance.calculate_aitchson_scores_for_tracks(synth_df, neighbor_df)

        assert len(result[1000]) == 4

    def test_score_tuples_format(self, ts_instance):
        synth_df = _make_synth_df(1)
        neighbor_df = _make_neighbor_df(2)
        result = ts_instance.calculate_aitchson_scores_for_tracks(synth_df, neighbor_df)

        for track_id, score in result[1000]:
            assert np.isscalar(track_id)
            assert np.isscalar(score) and float(score) >= 0

    def test_identical_genre_distributions_give_zero_distance(self, ts_instance):
        """If a neighbor has the exact same genre dist as the synthetic track, distance should be 0."""
        synth_df = _make_synth_df(1)
        # Clone synthetic row as a neighbor
        neighbor_df = synth_df.rename(columns={"synthetic_track_id": "track_id"})
        neighbor_df["track_id"] = 9999
        result = ts_instance.calculate_aitchson_scores_for_tracks(synth_df, neighbor_df)

        _, score = result[1000][0]
        assert score == pytest.approx(0.0, abs=1e-10)

    def test_empty_neighbors_returns_empty_list(self, ts_instance):
        synth_df = _make_synth_df(1)
        neighbor_df = _make_neighbor_df(0)
        result = ts_instance.calculate_aitchson_scores_for_tracks(synth_df, neighbor_df)

        assert result[1000] == []


# ============================
# 6) TrackSimilarity __init__ + extract_features (DB mocked)
# ============================

class TestTrackSimilarityInit:
    @patch("models.track_similarity.get_pg_conn")
    def test_init_with_none_defaults_to_empty(self, mock_conn):
        """When frontend_inputs is None, inputs should default to empty list."""
        mock_conn.return_value = MagicMock()

        with patch.object(TrackSimilarity, "extract_features", return_value=(_make_synth_df(0), _make_neighbor_df(0))):
            with patch.object(TrackSimilarity, "calculate_aitchson_scores_for_tracks", return_value={}):
                with patch.object(TrackSimilarity, "sort_similarity_scores", return_value={}):
                    ts = TrackSimilarity(None)

        assert ts.inputs == []

    @patch("models.track_similarity.get_pg_conn")
    def test_init_stores_sorted_genre_scores(self, mock_conn):
        mock_conn.return_value = MagicMock()
        synth = _make_synth_df(1)
        neighbors = _make_neighbor_df(3)

        with patch.object(TrackSimilarity, "extract_features", return_value=(synth, neighbors)):
            ts = TrackSimilarity(["fake_id_1"])

        # sorted_genre_scores should be populated
        assert isinstance(ts.sorted_genre_scores, dict)
        # Each synth track should have neighbors sorted ascending
        for synth_id, scores in ts.sorted_genre_scores.items():
            score_vals = [s[1] for s in scores]
            assert score_vals == sorted(score_vals)

    def test_init_calls_extract_then_score_then_sort(self):
        """Verify __init__ orchestrates the pipeline: extract -> score -> sort."""
        synth = _make_synth_df(1)
        neighbors = _make_neighbor_df(2)

        with patch.object(TrackSimilarity, "extract_features", return_value=(synth, neighbors)) as mock_extract:
            with patch.object(TrackSimilarity, "calculate_aitchson_scores_for_tracks", return_value={"a": []}) as mock_calc:
                with patch.object(TrackSimilarity, "sort_similarity_scores", return_value={"a": []}) as mock_sort:
                    ts = TrackSimilarity(["id1"])

        mock_extract.assert_called_once()
        mock_calc.assert_called_once_with(synth, neighbors)
        mock_sort.assert_called_once()
