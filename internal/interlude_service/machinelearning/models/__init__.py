"""Model modules — lazy imports to avoid circular dependency.

link_predictor imports models.artist_similarity, so eagerly importing
link_predictor here would create a circular import cycle.
"""

__all__ = [
    'HopPredictor',
    'train_hop_predictor',
    'LinkPredictor',
    'train_link_predictor'
]
