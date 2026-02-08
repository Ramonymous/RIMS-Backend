"""FastAPI dependencies for authentication and authorization."""

import time
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_token
from app.models import User

# HTTP Bearer token scheme
bearer_scheme = HTTPBearer(auto_error=True)

_CURRENT_USER_CACHE_TTL_SECONDS = 10.0
_current_user_cache: dict[UUID, tuple[float, User]] = {}


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """
    Dependency to get the current authenticated user from JWT token.
    
    Raises HTTPException 401 if token is invalid or user not found.
    """
    token = credentials.credentials
    user_id = verify_token(token)
    
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        user_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    cached = _current_user_cache.get(user_uuid)
    now = time.monotonic()
    if cached is not None:
        cached_at, cached_user = cached
        if now - cached_at <= _CURRENT_USER_CACHE_TTL_SECONDS:
            return cached_user

    stmt = select(User).where(User.id == user_uuid)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    _current_user_cache[user_uuid] = (now, user)
    return user


# Type alias for dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(permission: str):
    """
    Factory for permission-checking dependency.
    
    Usage:
        @router.get("/admin", dependencies=[Depends(require_permission("admin"))])
    """
    async def check_permission(current_user: CurrentUser) -> User:
        if not current_user.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission} required",
            )
        return current_user
    
    return check_permission


def require_any_permission(*permissions: str):
    """
    Factory for checking if user has any of the specified permissions.
    """
    async def check_permissions(current_user: CurrentUser) -> User:
        for permission in permissions:
            if current_user.has_permission(permission):
                return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: one of {permissions} required",
        )
    
    return check_permissions
