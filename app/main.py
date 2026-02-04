"""FastAPI application entry point - Production optimized with auto environment detection."""

import logging
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator
from ipaddress import ip_address, ip_network

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.core.ratelimit import RateLimitMiddleware, RateLimitConfig
from app.routers import (
    auth,
    dashboard,
    events,
    movements,
    outgoings,
    parts,
    receivings,
    requests,
    users,
)

# Cloudflare IP Ranges (for validation in production)
CLOUDFLARE_IPV4 = [
    "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "104.16.0.0/13", "104.24.0.0/14", "108.162.192.0/18",
    "131.0.72.0/22", "141.101.64.0/18", "162.158.0.0/15",
    "172.64.0.0/13", "173.245.48.0/20", "188.114.96.0/20",
    "190.93.240.0/20", "197.234.240.0/22", "198.41.128.0/17",
]

CLOUDFLARE_IPV6 = [
    "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32",
    "2405:b500::/32", "2405:8100::/32", "2a06:98c0::/29",
    "2c0f:f248::/32",
]

# Configure logging
log_format = (
    "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s"
)
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format=log_format,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Suppress noisy loggers in production
if settings.is_production:
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)


def is_cloudflare_ip(ip: str) -> bool:
    """Check if IP is from Cloudflare network."""
    try:
        addr = ip_address(ip)
        ranges = CLOUDFLARE_IPV4 if addr.version == 4 else CLOUDFLARE_IPV6
        return any(addr in ip_network(cidr) for cidr in ranges)
    except ValueError:
        logger.warning(f"Invalid IP address: {ip}")
        return False


async def verify_database_connection() -> bool:
    """Verify database connection on startup."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("? Database connection verified")
        return True
    except Exception as e:
        logger.error(f"? Database connection failed: {e}")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage app startup and shutdown events."""
    # Startup
    logger.info("=" * 60)
    logger.info(f"?? Starting {settings.app_name}...")
    logger.info(f"   Environment: {settings.environment.upper()}")
    logger.info(f"   Version: {settings.app_version}")
    
    # Verify database connection
    db_ok = await verify_database_connection()
    if not db_ok:
        logger.warning("??  Database connection failed - some features may not work")
    
    # Log configuration
    logger.info("?? Configuration:")
    logger.info(f"   Debug Mode: {settings.debug}")
    logger.info(f"   API Domain: {settings.api_domain}")
    logger.info(f"   Frontend Domain: {settings.frontend_domain}")
    logger.info(f"   CORS Origins: {settings.allowed_origins_list}")
    logger.info(f"   Cloudflare Validation: {settings.should_validate_cloudflare}")
    logger.info(f"   Rate Limiting: {settings.rate_limit_enabled}")
    
    if settings.is_development:
        logger.info(f"?? API Docs: http://localhost:{settings.port}/docs")
        logger.info(f"?? Debug Info: http://localhost:{settings.port}/info")
    
    logger.info("=" * 60)
    
    yield
    
    # Shutdown
    logger.info("=" * 60)
    logger.info(f"?? Shutting down {settings.app_name}...")
    await engine.dispose()
    logger.info("? Resources cleaned up")
    logger.info("=" * 60)


app = FastAPI(
    title=settings.app_name,
    description="FastAPI backend for ProjectRIMS - Inventory Management System",
    version=settings.app_version,
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
    # Conditionally enable docs based on environment
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
    openapi_url="/openapi.json" if settings.is_development else None,
)

# ============================================================================
# MIDDLEWARE CONFIGURATION (Order matters! Last added = First executed)
# ============================================================================

# 1. Trusted Host Middleware (First line of defense)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.allowed_hosts,
)

# 2. CORS Middleware (Handle preflight requests early)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,  # Cache preflight for 1 hour
)

# 3. GZip Middleware (Compress responses - backup to Caddy)
app.add_middleware(GZipMiddleware, minimum_size=500)

# 4. Rate Limiting Middleware (Apply rate limits)
if settings.rate_limit_enabled:
    app.add_middleware(
        RateLimitMiddleware,
        config=RateLimitConfig(
            requests_per_minute=settings.rate_limit_per_minute,
            requests_per_second=settings.rate_limit_per_second,
            auth_requests_per_minute=settings.rate_limit_auth_per_minute,
        ),
    )


# ============================================================================
# CUSTOM MIDDLEWARE
# ============================================================================

@app.middleware("http")
async def cloudflare_middleware(request: Request, call_next):
    """
    Extract real client IP and Cloudflare metadata.
    Validate requests are from Cloudflare in production.
    """
    # Get client IP from proxy
    proxy_ip = request.client.host if request.client else "unknown"
    
    # Validate Cloudflare IP in production
    if settings.should_validate_cloudflare and proxy_ip != "unknown":
        if not is_cloudflare_ip(proxy_ip):
            logger.warning(
                f"??  Request NOT from Cloudflare: {proxy_ip} "
                f"(Host: {request.headers.get('host', 'unknown')})"
            )
            # In strict mode, you can block non-Cloudflare requests
            # return JSONResponse(
            #     status_code=403,
            #     content={"detail": "Direct access forbidden"}
            # )
    
    # Extract real client IP from Cloudflare headers
    # Priority: CF-Connecting-IP > X-Real-IP > X-Forwarded-For > client IP
    cf_connecting_ip = request.headers.get("CF-Connecting-IP")
    x_real_ip = request.headers.get("X-Real-IP")
    x_forwarded_for = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    
    real_ip = (
        cf_connecting_ip
        or x_real_ip
        or x_forwarded_for
        or proxy_ip
    )
    
    # Extract Cloudflare metadata
    cf_ray = request.headers.get("CF-Ray", "N/A")
    cf_country = request.headers.get("CF-IPCountry", "Unknown")
    cf_visitor = request.headers.get("CF-Visitor", "{}")
    
    # Attach to request state for easy access
    request.state.real_ip = real_ip
    request.state.proxy_ip = proxy_ip
    request.state.cf_ray = cf_ray
    request.state.cf_country = cf_country
    request.state.cf_visitor = cf_visitor
    request.state.is_cloudflare = bool(cf_connecting_ip)
    
    # Log request in debug mode
    if settings.debug:
        logger.debug(
            f"Request: {request.method} {request.url.path} | "
            f"Real IP: {real_ip} | Country: {cf_country} | "
            f"CF-Ray: {cf_ray}"
        )
    
    response = await call_next(request)
    
    # Add custom headers to response
    response.headers["X-Environment"] = settings.environment
    response.headers["X-API-Version"] = settings.app_version
    
    return response


# ============================================================================
# EXCEPTION HANDLERS
# ============================================================================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle validation errors with structured response."""
    logger.warning(
        f"Validation error from {request.state.real_ip} "
        f"[{request.method} {request.url.path}]: {exc.errors()}"
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Validation error",
            "errors": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Handle unexpected errors."""
    logger.error(
        f"Unexpected error from {request.state.real_ip} "
        f"[CF-Ray: {request.state.cf_ray}] "
        f"[{request.method} {request.url.path}]: {exc}",
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "message": str(exc) if settings.debug else "An unexpected error occurred",
        },
    )


# ============================================================================
# ROUTERS
# ============================================================================

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(users.router)
app.include_router(parts.router)
app.include_router(movements.router)
app.include_router(receivings.router)
app.include_router(outgoings.router)
app.include_router(requests.router)
app.include_router(events.router)


# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/", response_class=ORJSONResponse, tags=["Root"])
async def root(request: Request) -> dict[str, Any]:
    """Root endpoint - API information."""
    return {
        "message": f"{settings.app_name} is running",
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
        "docs": "/docs" if settings.is_development else "disabled",
        "redoc": "/redoc" if settings.is_development else "disabled",
    }


@app.get("/health", response_class=ORJSONResponse, tags=["Health"])
async def health_check(request: Request) -> dict[str, Any]:
    """
    Health check endpoint for monitoring and load balancers.
    Returns database connection status.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        
        return {
            "status": "healthy",
            "database": "connected",
            "version": settings.app_version,
            "environment": settings.environment,
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(e) if settings.debug else "Database connection failed",
            },
        )


@app.get("/info", response_class=ORJSONResponse, tags=["Debug"])
async def server_info(request: Request) -> dict[str, Any]:
    """
    Get server and request info (development only).
    Useful for debugging Cloudflare setup and IP forwarding.
    """
    if not settings.is_development:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": "This endpoint is only available in development mode"},
        )
    
    return {
        "environment": settings.environment,
        "request_info": {
            "real_ip": request.state.real_ip,
            "proxy_ip": request.state.proxy_ip,
            "is_cloudflare": request.state.is_cloudflare,
        },
        "cloudflare_info": {
            "cf_ray": request.state.cf_ray,
            "cf_country": request.state.cf_country,
            "cf_visitor": request.state.cf_visitor,
        },
        "headers": {
            k: v for k, v in request.headers.items()
            if k.lower().startswith(("cf-", "x-"))
        },
        "settings": {
            "api_domain": settings.api_domain,
            "frontend_domain": settings.frontend_domain,
            "debug": settings.debug,
            "cloudflare_validation": settings.should_validate_cloudflare,
        },
    }


@app.get("/ping", response_class=ORJSONResponse, tags=["Health"])
async def ping() -> dict[str, str]:
    """Simple ping endpoint for uptime monitoring."""
    return {"message": "pong"}