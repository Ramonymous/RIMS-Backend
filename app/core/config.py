"""Configuration management for the FastAPI application."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

# Jakarta timezone (UTC+7)
TIMEZONE = ZoneInfo("Asia/Jakarta")


def now_jakarta() -> datetime:
    """Get current datetime in Asia/Jakarta timezone as naive datetime."""
    # Return naive datetime for PostgreSQL TIMESTAMP WITHOUT TIME ZONE
    return datetime.now(TIMEZONE).replace(tzinfo=None)


def to_jakarta(dt: datetime) -> datetime:
    """Convert a datetime to Asia/Jakarta timezone."""
    if dt.tzinfo is None:
        # Assume UTC if naive
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TIMEZONE)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # App Info
    app_name: str = "ProjectRIMS API"
    app_version: str = "0.1.0"
    
    # Environment Detection
    environment: str = "development"  # development, production, staging
    debug: bool = False
    
    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    
    # Database
    database_url: str
    
    # Security
    secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24
    
    # CORS Configuration
    allowed_origins: str = "http://localhost:3000,http://localhost:5173,https://rims.r-dev.asia"
    
    # Domain Configuration
    api_domain: str = "api.r-dev.asia"
    frontend_domain: str = "rims.r-dev.asia"
    
    REFRESH_SECRET_KEY: str = os.getenv("REFRESH_SECRET_KEY", "refresh_secret")
    REFRESH_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_MINUTES", 43200))
    timezone: str = "Asia/Jakarta"
    
    # Rate Limiting
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 120
    rate_limit_per_second: int = 20
    rate_limit_auth_per_minute: int = 10
    
    # Cloudflare
    cloudflare_enabled: bool = False  # Auto-detect from headers
    validate_cloudflare_ip: bool = True  # Only in production
    
    # Logging
    log_level: str = "INFO"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
    )
    
    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment.lower() == "production"
    
    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.environment.lower() == "development"
    
    @property
    def allowed_origins_list(self) -> List[str]:
        """Parse allowed origins from comma-separated string."""
        return [origin.strip() for origin in self.allowed_origins.split(",")]
    
    @property
    def allowed_hosts(self) -> List[str]:
        """Get allowed hosts based on environment."""
        if self.is_development:
            return ["*"]  # Allow all in development
        return [
            self.api_domain,
            self.frontend_domain,
            "localhost",
            "127.0.0.1",
        ]
    
    @property
    def should_validate_cloudflare(self) -> bool:
        """Should validate Cloudflare IPs."""
        return self.is_production and self.validate_cloudflare_ip


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()  # type: ignore[call-arg]


settings = get_settings()