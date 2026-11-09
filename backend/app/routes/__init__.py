"""HTTP routing.

Two routers, mounted by ``app.main.create_app``:

* ``system.router``: unversioned operational endpoints (``/``, ``/health``,
  ``/health/ready``). Mounted at the root.
* ``api_router``: every versioned business endpoint, mounted once at
  ``settings.API_V1_PREFIX`` (``/api/v1``). Feature routers are added here as
  they are built and so inherit the prefix automatically. Present: auth (P-6).
  Later: users, beneficiaries, transactions, risk, dashboard, alerts.

Routers validate input, call one service method and shape the response;
business logic never lives here.
"""

from fastapi import APIRouter

from app.routes import auth, system

api_router = APIRouter()
api_router.include_router(auth.router)  # /api/v1/auth/...

__all__ = ["api_router", "auth", "system"]
