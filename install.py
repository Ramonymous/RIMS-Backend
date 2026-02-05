"""
ProjectRIMS Installation Script
Interactive setup similar to Laravel Artisan
Enhanced for production deployment with environment selection
"""

from __future__ import annotations

import asyncio
import io
import os
import secrets
import subprocess
import sys
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Fix Windows encoding issues
if sys.platform == "win32":
    os.system("chcp 65001 >nul")
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


# Check for required packages BEFORE proceeding
REQUIRED_PACKAGES: dict[str, str] = {
    "asyncpg": "asyncpg",
    "sqlalchemy": "sqlalchemy",
    "pydantic": "pydantic",
    "pydantic_settings": "pydantic-settings",
    "dotenv": "python-dotenv",
    "jose": "python-jose",
    "passlib": "passlib",
    "cryptography": "cryptography",
    "orjson": "orjson",
}


def check_dependencies() -> bool:
    """Check if all required packages are installed."""
    missing: list[str] = []
    for module_name, package_name in REQUIRED_PACKAGES.items():
        try:
            __import__(module_name)
        except ImportError:
            missing.append(package_name)

    if missing:
        print("? Missing required dependencies:\n")
        for pkg in missing:
            print(f"   - {pkg}")
        print("\n?? Install missing packages:")
        print("   pip install -r requirements.txt\n")
        return False
    return True


if not check_dependencies():
    sys.exit(1)

# Now safe to import after dependency check
import asyncpg  # type: ignore[import-untyped]


class Colors:
    """Terminal colors."""

    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"


@dataclass
class DatabaseConfig:
    """Database configuration."""

    host: str
    port: int
    user: str
    password: str
    database: str

    @property
    def url(self) -> str:
        """Build async database URL."""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"

    @classmethod
    def from_url(cls, url: str) -> DatabaseConfig:
        """Parse database config from URL."""
        parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://"))
        return cls(
            host=parsed.hostname or "localhost",
            port=parsed.port or 5432,
            user=parsed.username or "postgres",
            password=parsed.password or "",
            database=parsed.path.lstrip("/") or "project_rims",
        )


def print_header(text: str) -> None:
    """Print a header."""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}{Colors.ENDC}\n")


def print_success(text: str) -> None:
    """Print success message."""
    print(f"{Colors.OKGREEN}? {text}{Colors.ENDC}")


def print_error(text: str) -> None:
    """Print error message."""
    print(f"{Colors.FAIL}? {text}{Colors.ENDC}")


def print_info(text: str) -> None:
    """Print info message."""
    print(f"{Colors.OKCYAN}?  {text}{Colors.ENDC}")


def print_warning(text: str) -> None:
    """Print warning message."""
    print(f"{Colors.WARNING}?  {text}{Colors.ENDC}")


def get_input(prompt: str, default: str | None = None) -> str:
    """Get user input with optional default."""
    if default:
        user_input = input(f"{prompt} [{default}]: ").strip()
        return user_input if user_input else default
    return input(f"{prompt}: ").strip()


def select_environment() -> str:
    """Select deployment environment."""
    print_header("Environment Selection")
    
    print("Select your deployment environment:\n")
    print("  1. Development (local machine)")
    print("  2. Production (VPS/server)")
    print("  3. Staging (testing server)")
    
    choice = get_input("\nSelect environment (1-3)", "1")
    
    env_map = {
        "1": "development",
        "2": "production",
        "3": "staging",
    }
    
    environment = env_map.get(choice, "development")
    print_info(f"Environment: {environment}")
    
    return environment


def create_env_file(environment: str) -> DatabaseConfig | None:
    """Create .env file interactively based on environment."""
    print_header("Environment Configuration")

    env_path = Path(".env")

    if env_path.exists():
        overwrite = get_input("??  .env file already exists. Overwrite? (yes/no)", "no").lower()
        if overwrite not in ("yes", "y"):
            print_info("Using existing .env file")
            return None

    is_production = environment == "production"
    is_development = environment == "development"

    print(f"\n?? Let's configure your {environment} environment:\n")

    # App Info
    print(f"{Colors.BOLD}Application:{Colors.ENDC}")
    app_name = get_input("App name", "ProjectRIMS API")
    app_version = get_input("App version", "0.1.0")

    # Database configuration
    print(f"\n{Colors.BOLD}Database Configuration:{Colors.ENDC}")
    db_host = get_input("Database host", "localhost")
    db_port = get_input("Database port", "5432")
    db_user = get_input("Database user", "postgres")
    db_password = getpass("Database password: ")
    db_name = get_input("Database name", "project_rims")

    # Security
    print(f"\n{Colors.BOLD}Security:{Colors.ENDC}")
    secret_key = secrets.token_urlsafe(32)
    print_info(f"Generated secret key: {secret_key[:20]}...")
    custom_secret = get_input("Use custom secret key? (leave empty to use generated)", "")
    if custom_secret:
        secret_key = custom_secret

    # Refresh Token
    print(f"\n{Colors.BOLD}Refresh Token:{Colors.ENDC}")
    refresh_secret = secrets.token_urlsafe(32)
    print_info(f"Generated refresh secret: {refresh_secret[:20]}...")
    custom_refresh = get_input("Use custom refresh secret? (leave empty to use generated)", "")
    if custom_refresh:
        refresh_secret = custom_refresh
    refresh_expiry = get_input("Refresh token expiry (minutes)", "43200")
    
    jwt_algorithm = get_input("JWT algorithm", "HS256")
    jwt_expiration = get_input("JWT expiration (hours)", "24")

    # CORS origins
    print(f"\n{Colors.BOLD}CORS Configuration:{Colors.ENDC}")
    if is_development:
        default_origins = "http://localhost:3000,http://localhost:5173,http://localhost:8080"
    else:
        default_origins = "https://rims.r-dev.asia"
    
    allowed_origins = get_input("Allowed origins (comma-separated)", default_origins)

    # Domain configuration (production only)
    if is_production:
        print(f"\n{Colors.BOLD}Domain Configuration:{Colors.ENDC}")
        api_domain = get_input("API domain", "api.r-dev.asia")
        frontend_domain = get_input("Frontend domain", "rims.r-dev.asia")
    else:
        api_domain = "localhost"
        frontend_domain = "localhost"

    # Cloudflare settings
    print(f"\n{Colors.BOLD}Cloudflare:{Colors.ENDC}")
    if is_production:
        cloudflare_enabled = get_input("Enable Cloudflare integration? (yes/no)", "yes").lower()
        validate_cf_ip = get_input("Validate Cloudflare IPs? (yes/no)", "yes").lower()
    else:
        cloudflare_enabled = "no"
        validate_cf_ip = "no"
        print_info("Cloudflare disabled in development mode")

    # Rate limiting
    print(f"\n{Colors.BOLD}Rate Limiting:{Colors.ENDC}")
    if is_development:
        rate_limit_enabled = get_input("Enable rate limiting? (yes/no)", "yes").lower()
        rate_per_min = get_input("Requests per minute", "200")
        rate_per_sec = get_input("Requests per second", "50")
        rate_auth_per_min = get_input("Auth requests per minute", "20")
    else:
        rate_limit_enabled = "yes"
        rate_per_min = get_input("Requests per minute", "120")
        rate_per_sec = get_input("Requests per second", "20")
        rate_auth_per_min = get_input("Auth requests per minute", "10")

    # Build config
    db_config = DatabaseConfig(
        host=db_host,
        port=int(db_port),
        user=db_user,
        password=db_password,
        database=db_name,
    )

    # Write .env file
    env_content = f"""# Environment
ENVIRONMENT={environment}
DEBUG={'true' if is_development else 'false'}

# App Info
APP_NAME={app_name}
APP_VERSION={app_version}

# Server
HOST=0.0.0.0
PORT=8000

# Database
DATABASE_URL={db_config.url}

# Security
SECRET_KEY={secret_key}
JWT_ALGORITHM={jwt_algorithm}
JWT_EXPIRATION_HOURS={jwt_expiration}

# Refresh Token
REFRESH_SECRET_KEY={refresh_secret}
REFRESH_TOKEN_EXPIRE_MINUTES={refresh_expiry}

# CORS
ALLOWED_ORIGINS={allowed_origins}

# Domains
API_DOMAIN={api_domain}
FRONTEND_DOMAIN={frontend_domain}

# Timezone
TIMEZONE=Asia/Jakarta

# Cloudflare
CLOUDFLARE_ENABLED={'true' if cloudflare_enabled in ('yes', 'y') else 'false'}
VALIDATE_CLOUDFLARE_IP={'true' if validate_cf_ip in ('yes', 'y') else 'false'}

# Rate Limiting
RATE_LIMIT_ENABLED={'true' if rate_limit_enabled in ('yes', 'y') else 'false'}
RATE_LIMIT_PER_MINUTE={rate_per_min}
RATE_LIMIT_PER_SECOND={rate_per_sec}
RATE_LIMIT_AUTH_PER_MINUTE={rate_auth_per_min}

# Logging
LOG_LEVEL={'DEBUG' if is_development else 'INFO'}
"""

    env_path.write_text(env_content)
    print_success(".env file created successfully!")
    
    # Save as .example template (for git)
    template_path = Path(f".env.{environment}.example")
    
    # Replace sensitive values in template
    template_content = env_content
    template_content = template_content.replace(db_config.password, "your-database-password")
    template_content = template_content.replace(secret_key, "CHANGE-THIS-TO-SECURE-RANDOM-KEY")
    
    template_path.write_text(template_content)
    print_info(f"Template saved to .env.{environment}.example (safe to commit)")

    return db_config


async def get_postgres_connection(
    db_config: DatabaseConfig, database: str = "postgres"
) -> Any:
    """Get a connection to PostgreSQL."""
    return await asyncpg.connect(  # type: ignore[no-any-return]
        host=db_config.host,
        port=db_config.port,
        user=db_config.user,
        password=db_config.password,
        database=database,
        timeout=10,
    )


async def check_postgres_connection(db_config: DatabaseConfig) -> bool:
    """Check if PostgreSQL server is accessible."""
    print_header("Checking PostgreSQL Connection")

    try:
        conn = await get_postgres_connection(db_config)
        version = await conn.fetchval("SELECT version()")
        await conn.close()
        
        print_success(f"Connected to PostgreSQL at {db_config.host}:{db_config.port}")
        if version:
            version_str = str(version)[:60]
            print_info(f"PostgreSQL: {version_str}...")
        return True
    except asyncpg.InvalidPasswordError:
        print_error("Invalid database password")
        return False
    except asyncpg.InvalidCatalogNameError:
        print_error("PostgreSQL server not accessible")
        return False
    except Exception as e:
        print_error(f"Cannot connect to PostgreSQL: {e}")
        print_info("\nPlease ensure:")
        print_info("  1. PostgreSQL is installed and running")
        print_info(f"  2. PostgreSQL is listening on {db_config.host}:{db_config.port}")
        print_info(f"  3. User '{db_config.user}' exists with correct password")
        return False


async def create_database(db_config: DatabaseConfig) -> bool:
    """Create database if it doesn't exist."""
    print_header("Database Creation")

    try:
        conn = await get_postgres_connection(db_config)

        # Check if database exists
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", db_config.database
        )

        if exists:
            print_info(f"Database '{db_config.database}' already exists")
        else:
            # Create database (safe identifier escaping)
            await conn.execute(f'CREATE DATABASE "{db_config.database}"')
            print_success(f"Database '{db_config.database}' created successfully!")

        await conn.close()
        return True

    except Exception as e:
        print_error(f"Failed to create database: {e}")
        return False


async def test_database_connection() -> bool:
    """Test connection to the application database."""
    print_header("Testing Database Connection")

    try:
        # Import engine here after .env is created
        from sqlalchemy import text

        from app.core.database import engine

        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT current_database(), version()"))
            row = result.fetchone()

            if row:
                print_success("Database connection successful!")
                print_info(f"Database: {row[0]}")
                version_str = str(row[1])[:60] if row[1] else "Unknown"
                print_info(f"PostgreSQL: {version_str}...")
            return True
    except Exception as e:
        print_error(f"Database connection failed: {e}")
        print_info("Make sure your .env file is configured correctly")
        return False


async def run_migrations() -> bool:
    """Run database migrations."""
    print_header("Running Database Migrations")

    try:
        # Check if alembic is initialized
        alembic_ini = Path("alembic.ini")
        if not alembic_ini.exists():
            print_error("alembic.ini not found. Run 'alembic init migrations' first")
            return False

        # Check current migration status
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "current"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            current = result.stdout.strip()
            if current and "(head)" in current:
                print_info("Database is already up to date")
                return True

        # Run migrations
        print_info("Applying migrations...")
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            print_success("Migrations applied successfully!")

            # Show table count
            from sqlalchemy import text

            from app.core.database import engine

            async with engine.connect() as conn:
                result_query = await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'"
                    )
                )
                table_count = result_query.scalar()
                print_info(f"Tables created: {table_count}")

            return True
        else:
            print_error(f"Migration failed: {result.stderr}")
            return False

    except Exception as e:
        print_error(f"Failed to run migrations: {e}")
        return False


async def create_admin_user() -> bool:
    """Create an admin user."""
    print_header("Create Admin User")

    create = get_input("Create admin user? (yes/no)", "yes").lower()
    if create not in ("yes", "y"):
        print_info("Skipping admin user creation")
        return True

    print("\n?? Admin User Details:\n")
    name = get_input("Name", "Admin")
    email = get_input("Email", "admin@projectrims.local")
    password = getpass("Password (min 8 characters): ")

    if len(password) < 8:
        print_error("Password must be at least 8 characters")
        return False

    confirm_password = getpass("Confirm password: ")

    if password != confirm_password:
        print_error("Passwords do not match")
        return False

    try:
        import uuid

        from sqlalchemy import select

        from app.core.database import AsyncSessionLocal
        from app.core.security import hash_password
        from app.models import User

        async with AsyncSessionLocal() as session:  # type: ignore[attr-defined]
            # Check if user exists
            result = await session.execute(  # type: ignore[union-attr]
                select(User).where(User.email == email)
            )
            existing_user = result.scalar_one_or_none()  # type: ignore[union-attr]

            if existing_user:
                print_warning(f"User with email '{email}' already exists")
                return True

            # Create admin user with all permissions
            admin_permissions = [
                "users.view",
                "users.create",
                "users.update",
                "users.delete",
                "parts.view",
                "parts.create",
                "parts.update",
                "parts.delete",
                "receivings.view",
                "receivings.create",
                "receivings.update",
                "receivings.delete",
                "receivings.complete",
                "receivings.cancel",
                "receivings.confirm_gr",
                "outgoings.view",
                "outgoings.create",
                "outgoings.update",
                "outgoings.delete",
                "outgoings.complete",
                "outgoings.cancel",
                "outgoings.confirm_gi",
                "requests.view",
                "requests.create",
                "requests.update",
                "requests.delete",
                "requests.complete",
                "requests.cancel",
                "requests.supply",
                "requests.locations",
            ]

            user = User(
                id=uuid.uuid4(),
                name=name,
                email=email,
                password=hash_password(password),
                permissions=admin_permissions,
            )

            session.add(user)  # type: ignore[union-attr]
            await session.commit()  # type: ignore[union-attr]

            print_success(f"Admin user '{email}' created successfully!")
            print_info(f"Permissions granted: {len(admin_permissions)}")
            return True

    except Exception as e:
        print_error(f"Failed to create admin user: {e}")
        import traceback
        traceback.print_exc()
        return False


def print_summary(environment: str) -> None:
    """Print installation summary."""
    print_header("Installation Complete!")

    print(f"{Colors.OKGREEN}{Colors.BOLD}")
    print("  ? Environment configured")
    print("  ? Database created and migrated")
    print("  ? Admin user created")
    print(f"{Colors.ENDC}")

    print(f"\n{Colors.BOLD}Environment: {environment.upper()}{Colors.ENDC}\n")

    if environment == "development":
        print(f"{Colors.BOLD}Next Steps:{Colors.ENDC}\n")
        print("  1. Start the development server:")
        print(f"     {Colors.OKCYAN}uvicorn app.main:app --reload{Colors.ENDC}\n")
        print("  2. Access the API documentation:")
        print(f"     {Colors.OKCYAN}http://localhost:8000/docs{Colors.ENDC}\n")
        print("  3. Test the API:")
        print(f"     {Colors.OKCYAN}curl http://localhost:8000{Colors.ENDC}\n")
        print("  4. Debug endpoint (dev only):")
        print(f"     {Colors.OKCYAN}curl http://localhost:8000/info{Colors.ENDC}\n")
    else:
        print(f"{Colors.BOLD}Production Deployment:{Colors.ENDC}\n")
        print("  1. Configure systemd service:")
        print(f"     {Colors.OKCYAN}sudo systemctl enable projectrims-api{Colors.ENDC}\n")
        print("  2. Start the service:")
        print(f"     {Colors.OKCYAN}sudo systemctl start projectrims-api{Colors.ENDC}\n")
        print("  3. Check status:")
        print(f"     {Colors.OKCYAN}sudo systemctl status projectrims-api{Colors.ENDC}\n")
        print("  4. View logs:")
        print(f"     {Colors.OKCYAN}journalctl -u projectrims-api -f{Colors.ENDC}\n")
        print("  5. Test the API:")
        print(f"     {Colors.OKCYAN}curl https://api.r-dev.asia/health{Colors.ENDC}\n")


async def main() -> bool:
    """Main installation flow."""
    print(
        f"""
{Colors.HEADER}{Colors.BOLD}
{'=' * 60}
  ProjectRIMS Installation Wizard
  FastAPI Backend Setup & Configuration Tool
{'=' * 60}
{Colors.ENDC}
"""
    )

    print("Welcome! This wizard will help you set up ProjectRIMS.\n")

    # Step 1: Select environment
    environment = select_environment()

    # Step 2: Create .env file
    db_config = create_env_file(environment)

    if db_config is None:
        # .env exists, parse it to get database config
        from dotenv import load_dotenv

        load_dotenv()
        database_url = os.getenv("DATABASE_URL")

        if not database_url:
            print_error("DATABASE_URL not found in .env file")
            return False

        db_config = DatabaseConfig.from_url(database_url)

    # Step 3: Check PostgreSQL connection
    if not await check_postgres_connection(db_config):
        print_error("Cannot proceed without PostgreSQL connection")
        return False

    # Step 4: Create database
    if not await create_database(db_config):
        print_error("Cannot proceed without database")
        return False

    # Step 5: Test application database connection
    if not await test_database_connection():
        print_error("Cannot connect to application database")
        return False

    # Step 6: Run migrations
    if not await run_migrations():
        print_error("Migration failed")
        return False

    # Step 7: Create admin user
    if not await create_admin_user():
        print_warning("Admin user creation skipped or failed")

    # Summary
    print_summary(environment)

    return True


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print(f"\n\n{Colors.WARNING}Installation cancelled by user{Colors.ENDC}")
        sys.exit(1)
    except Exception as e:
        print_error(f"Installation failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)