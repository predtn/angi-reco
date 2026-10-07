from enum import StrEnum


class DishVectorStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class FeedbackType(StrEnum):
    LIKE = "like"
    DISLIKE = "dislike"


class RecoContext(StrEnum):
    LIST = "list"
    HOME = "home"
    ROLL = "roll"
    ROADMAP_MANUAL = "roadmap_manual"
    ROADMAP_AI = "roadmap_ai"
