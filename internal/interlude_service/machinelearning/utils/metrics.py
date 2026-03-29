"""
Utility functions for computing distances and similarities
"""
import numpy as np


def l2_normalize(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """Row-wise L2 normalization."""
    norm = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / (norm + eps)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """
    Cosine similarity between a and b.
    a, b can be shape (d,) or (n, d)
    Returns scalar or (n,)
    """
    a = np.atleast_2d(a)
    b = np.atleast_2d(b)
    return np.sum(a * b, axis=1)


def cosine_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Cosine distance = 1 - cosine similarity."""
    return 1.0 - cosine_similarity(a, b)


def l2_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Euclidean (L2) distance."""
    a = np.atleast_2d(a)
    b = np.atleast_2d(b)
    return np.linalg.norm(a - b, axis=1)


def l1_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Manhattan (L1) distance."""
    a = np.atleast_2d(a)
    b = np.atleast_2d(b)
    return np.sum(np.abs(a - b), axis=1)


def dot_product(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Dot product."""
    a = np.atleast_2d(a)
    b = np.atleast_2d(b)
    return np.sum(a * b, axis=1)
