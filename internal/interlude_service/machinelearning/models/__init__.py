"""Model modules"""
from .hop_predictor import HopPredictor, train_hop_predictor
from .link_predictor import LinkPredictor, train_link_predictor

__all__ = [
    'HopPredictor',
    'train_hop_predictor',
    'LinkPredictor',
    'train_link_predictor'
]
