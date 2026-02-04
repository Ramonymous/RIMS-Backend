"""Rate limiting middleware using in-memory storage."""

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Awaitable, Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    requests_per_minute: int = 60
    requests_per_second: int = 10
    auth_requests_per_minute: int = 10  # Stricter for auth endpoints


class InMemoryRateLimiter:
    """
    Simple in-memory rate limiter using sliding window.
    
    For production, consider using Redis-based rate limiting.
    """
    
    def __init__(self):
        self._requests: dict[str, list[float]] = defaultdict(list)
    
    def _cleanup_old_requests(self, key: str, window_seconds: float) -> None:
        """Remove requests older than the window."""
        now = time.time()
        cutoff = now - window_seconds
        self._requests[key] = [t for t in self._requests[key] if t > cutoff]
    
    def is_allowed(self, key: str, max_requests: int, window_seconds: float) -> bool:
        """Check if request is allowed under rate limit."""
        self._cleanup_old_requests(key, window_seconds)
        
        if len(self._requests[key]) >= max_requests:
            return False
        
        self._requests[key].append(time.time())
        return True
    
    def get_retry_after(self, key: str, window_seconds: float) -> int:
        """Get seconds until the oldest request expires."""
        if not self._requests[key]:
            return 0
        oldest = min(self._requests[key])
        retry_after = int(window_seconds - (time.time() - oldest)) + 1
        return max(0, retry_after)


# Global rate limiter instance
rate_limiter = InMemoryRateLimiter()


def get_client_ip(request: Request) -> str:
    """Extract client IP from request, handling proxies."""
    # Check X-Forwarded-For header first (for reverse proxies)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    
    # Check X-Real-IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    # Fall back to direct client IP
    if request.client:
        return request.client.host
    
    return "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware with different limits for different endpoints.
    """
    
    def __init__(self, app: ASGIApp, config: RateLimitConfig | None = None):
        super().__init__(app)
        self.config = config or RateLimitConfig()
    
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Skip rate limiting for health checks and docs
        path = request.url.path
        if path in ("/health", "/", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)
        
        client_ip = get_client_ip(request)
        
        # Stricter rate limiting for auth endpoints
        if path.startswith("/auth"):
            key = f"auth:{client_ip}"
            max_requests = self.config.auth_requests_per_minute
            window = 60.0
        else:
            key = f"api:{client_ip}"
            max_requests = self.config.requests_per_minute
            window = 60.0
        
        if not rate_limiter.is_allowed(key, max_requests, window):
            retry_after = rate_limiter.get_retry_after(key, window)
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": "Rate limit exceeded",
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )
        
        return await call_next(request)
