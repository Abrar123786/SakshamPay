"""HTTP routers. One module per API group; routers validate input, call one service
method and shape the response. No business logic lives here.

``api_router`` is mounted at ``settings.API_V1_PREFIX`` (``/api/v1``). Later prompts
add the auth, users, beneficiaries, transactions, risk, dashboard and alerts routers.
"""

from fastapi import APIRouter

from app.routes import health

api_router = APIRouter()
api_router.include_router(health.router)

__all__ = ["api_router", "health"]
