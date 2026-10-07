from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """RECO-07. `status` is always "ok" while the service answers; `db` tells whether the
    database is reachable."""

    status: Literal["ok"] = "ok"
    db: Literal["ok", "error"]
    # null when the database is unreachable or has no active configuration (then 503)
    active_config_version: int | None
