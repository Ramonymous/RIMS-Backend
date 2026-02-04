"""Security utilities for password hashing and JWT token generation."""

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# Password hashing context - using argon2 for better security
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a password using Argon2."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: str, expires_hours: int | None = None) -> str:
    """Create a JWT access token for a user."""
    if expires_hours is None:
        expires_hours = settings.jwt_expiration_hours

    expire = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
    payload: dict[str, Any] = {"sub": user_id, "exp": expire}
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token


def verify_token(token: str) -> str | None:
    """Verify and decode a JWT token. Returns user_id if valid, None if invalid."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            return None
        return user_id
    except JWTError:
        return None


# Refresh token config
REFRESH_SECRET_KEY = getattr(settings, "REFRESH_SECRET_KEY", "refresh_secret")
REFRESH_TOKEN_EXPIRE_MINUTES = getattr(settings, "REFRESH_TOKEN_EXPIRE_MINUTES", 43200)

def create_refresh_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES)
    payload: dict[str, Any] = {"sub": subject, "exp": expire}
    return jwt.encode(payload, REFRESH_SECRET_KEY, algorithm="HS256")

def verify_refresh_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, REFRESH_SECRET_KEY, algorithms=["HS256"])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            return None
        return user_id
    except JWTError:
        return None
