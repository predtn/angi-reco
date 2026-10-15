from fastapi import APIRouter, Depends

from app.api.routes import dishes, feedback, health, recommendations, survey
from app.core.security import require_api_key

# Endpoints called by the backend and the outbox worker (RECO-01..06, RECO-09).
# Add their routers here; every one of them requires X-Api-Key.
protected_router = APIRouter(dependencies=[Depends(require_api_key)])
protected_router.include_router(dishes.router)
protected_router.include_router(feedback.router)
protected_router.include_router(recommendations.router)
protected_router.include_router(survey.router)

# Endpoints without X-Api-Key: only /health (RECO-07), polled by Render and the Admin.
public_router = APIRouter()
public_router.include_router(health.router)

api_router = APIRouter()
api_router.include_router(public_router)
api_router.include_router(protected_router)
