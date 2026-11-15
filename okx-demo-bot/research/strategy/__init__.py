from .base import Strategy, prepare_features
from .v1 import V1SMASpot
from .v2 import V2AdxZSpot
from .v3 import V3MacroFilter
from .v4 import V4SwapBidirectional

STRATEGIES = {
    "V1": V1SMASpot,
    "V2": V2AdxZSpot,
    "V3": V3MacroFilter,
    "V4": V4SwapBidirectional,
}

__all__ = [
    "Strategy",
    "prepare_features",
    "V1SMASpot",
    "V2AdxZSpot",
    "V3MacroFilter",
    "V4SwapBidirectional",
    "STRATEGIES",
]
