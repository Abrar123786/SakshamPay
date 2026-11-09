"""Reusable route dependencies.

``CurrentUser`` protects an endpoint: add a ``user: CurrentUser`` parameter and the
endpoint only runs for a request with a valid bearer token for an active user.
The user is identified from the token's ``sub`` claim only, never from the body,
query or path.

The token is checked before a database session is opened, so a missing or bad
token is rejected with 401 even when the database is down or not configured.
"""

import uuid
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import AuthenticationError, InvalidTokenError, decode_access_token
from app.database.session import DbSession
from app.models import User
from app.repositories import UserRepository

# auto_error=False: we raise our own errors in the standard format (FastAPI's default is a bare 403).
bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerToken",
    description="Access token from POST /api/v1/auth/login. Send as: Authorization: Bearer <token>",
)


def get_token_user_id(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> uuid.UUID:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError()
    return decode_access_token(credentials.credentials, request.app.state.settings)


def get_current_user(user_id: Annotated[uuid.UUID, Depends(get_token_user_id)], session: DbSession) -> User:
    user = UserRepository(session).get(user_id)
    if user is None or not user.is_active:
        # A valid signature for a user who no longer exists (or was deactivated) is still not access.
        raise InvalidTokenError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
