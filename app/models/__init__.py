"""ORM models of schema recommendation (ANGI_Data_Dictionary_Ver1.2, sheet Recommendation).

Importing this package registers every table on Base.metadata, which Alembic compares against.
"""

from app.models.algorithm import AlgorithmConfig, SurveyOptionVector
from app.models.dish import DishStats, DishVector
from app.models.interaction import InteractionEvent
from app.models.recommendation import RecommendationItem, RecommendationLog
from app.models.user import UserDishScore, UserPreferenceVector

__all__ = [
    "AlgorithmConfig",
    "DishStats",
    "DishVector",
    "InteractionEvent",
    "RecommendationItem",
    "RecommendationLog",
    "SurveyOptionVector",
    "UserDishScore",
    "UserPreferenceVector",
]
