# ProjectRIMS Backend API

FastAPI backend for the **R**eal-time **I**nventory **M**anagement **S**ystem (RIMS).

## Tech Stack

- **Framework**: FastAPI
- **Language**: Python 3.10+
- **Database**: PostgreSQL with asyncpg
- **ORM**: SQLAlchemy 2.0 (async)
- **Migrations**: Alembic
- **Authentication**: JWT (python-jose)
- **Password Hashing**: Argon2 (passlib)

## Quick Start

### Prerequisites
- Python 3.10+
- PostgreSQL database

### Setup

1. **Create virtual environment and install dependencies:**
   ```bash
   python -m venv venv
   venv\Scripts\activate  # Windows
   pip install -r requirements.txt
   ```

2. **Configure environment:**
   ```bash
   # Copy .env.example to .env and update with your database credentials
   copy .env.example .env
   ```

3. **Run the installation wizard (recommended):**
   ```bash
   python install.py
   ```
   This will guide you through:
   - Creating .env configuration
   - Verifying PostgreSQL connection
   - Creating the database
   - (Optional) Resetting the database (DROP & RECREATE)
   - Running migrations
   - Creating an admin user

4. **Or manually run the server:**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

The API will be available at `http://localhost:8000`

## API Base Paths

All application APIs are versioned and namespaced under `/v1`:

### Shared (global)

- `POST /v1/auth/login`
- `POST /v1/auth/refresh`
- `GET /v1/users`
- `GET /v1/users/me`

### Inventory

All inventory endpoints are under:

- `/v1/inventory/*`

Examples:

- `GET /v1/inventory/dashboard`
- `GET /v1/inventory/parts`
- `GET /v1/inventory/movements`
- `GET /v1/inventory/receivings`
- `GET /v1/inventory/outgoings`
- `GET /v1/inventory/requests`
- `GET /v1/inventory/events/stream`

### Delivery

- `/v1/delivery/*` (placeholder for now)

### API Documentation
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Project Structure

```
app/
├── main.py                    # FastAPI application entry point with optimized startup/shutdown
├── api/                        # Versioned API modules
│   └── v1/
│       ├── shared/             # Shared APIs (auth, users)
│       ├── inventory/          # Inventory APIs
│       └── delivery/           # Delivery APIs (placeholder)
├── core/                      # Core infrastructure
│   ├── config.py              # Environment settings and configuration management
│   ├── database.py            # Database connection and session management
│   └── security.py            # Password hashing and JWT token utilities
├── models/                    # SQLAlchemy ORM models
│   └── __init__.py            # User, Part, Receiving, Outgoing, Request, etc.
│   ├── shared.py              # Shared model exports (organizational)
│   ├── inventory.py           # Inventory model exports (organizational)
│   └── delivery.py            # Delivery model exports (placeholder)
├── schemas/                   # Pydantic request/response schemas
│   └── __init__.py            # Validation schemas for all resources
│   ├── shared.py              # Shared schema exports (organizational)
│   ├── inventory.py           # Inventory schema exports (organizational)
│   └── delivery.py            # Delivery schema exports (placeholder)
└── routers/                   # Compatibility re-exports (legacy imports)
```

## Roles

Users have a `role` field used by the frontend for routing and UI:

- `admin`
- `inventory`
- `delivery`

If you use `install.py` to create the bootstrap admin user, it will be created with `role="admin"`.

## Application Features

### Startup & Shutdown Management
- **Lifespan Context Manager**: Proper resource initialization and cleanup
- **Database Connection Verification**: Validates database connectivity on startup
- **Configuration Logging**: Displays API configuration at startup for debugging
- **Graceful Shutdown**: Cleans up database connections and resources

### Error Handling
- **Global Exception Handlers**: Centralized error handling for all endpoints
- **Validation Error Handler**: Structured validation error responses
- **Unexpected Error Handler**: Logs internal errors with full stack traces
- **Debug Mode Support**: Conditional error message detail based on `DEBUG` setting

### Health Monitoring
- **Root Endpoint** (`/`): Returns API information and documentation links
- **Health Check** (`/health`): Detailed health status including database connection
- **Database Status**: Health endpoint verifies database connectivity

### Middleware
- **CORS**: Configured for multi-origin support based on environment settings

## Database Migrations

Use Alembic for schema migrations:

```bash
# Create a new migration
alembic revision --autogenerate -m "Description"

# Apply migrations
alembic upgrade head

# Revert to previous migration
alembic downgrade -1
```

## Environment Variables

### Required
- `DATABASE_URL` - PostgreSQL connection string (format: `postgresql+asyncpg://user:password@host:port/dbname`)
- `SECRET_KEY` - JWT signing key for token authentication

### Optional
- `ALLOWED_ORIGINS` - CORS origins (default: `http://localhost:3000`)
- `JWT_ALGORITHM` - Algorithm for JWT tokens (default: `HS256`)
- `JWT_EXPIRATION_HOURS` - Token expiration time (default: `24`)
- `DEBUG` - Enable debug mode for detailed error messages (default: `false`)

## Notes

- All database operations use async/await with asyncpg driver
- Soft-delete pattern is used for most resources (deleted_at column)
- UUID is used as primary key for all models
- PartMovements table is append-only (immutable audit trail)
- Password hashing uses Argon2 via passlib
- JWT tokens use HS256 algorithm with configurable expiration
- All core infrastructure (config, database, security) is in `app/core/`
- Models and schemas are organized in dedicated modules for better maintainability
- Structured logging for debugging and monitoring
- Automatic resource cleanup on graceful shutdown

## Deployment (Linux VPS with Caddy)

### 1. Server Prerequisites

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python and dependencies
sudo apt install -y python3.11 python3.11-venv python3-pip postgresql postgresql-contrib

# Install Caddy
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

### 2. Create Application Directory

```bash
# Create directory structure
sudo mkdir -p /var/www/rims-backend
sudo chown $USER:$USER /var/www/rims-backend

# Transfer files from local machine
rsync -avz --exclude 'venv' --exclude '__pycache__' --exclude '.env' \
  ./ user@your-vps:/var/www/rims-backend/
```

### 3. Setup Python Environment

```bash
cd /var/www/rims-backend

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment

Create `/var/www/rims-backend/.env`:

```env
# Database
DATABASE_URL=postgresql+asyncpg://rims_user:your_secure_password@localhost:5432/rims_db

# Security
SECRET_KEY=your-super-secret-key-min-32-chars-long
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# CORS
ALLOWED_ORIGINS=https://rims.r-dev.asia

# Debug (set to false in production)
DEBUG=false
```

### 5. Setup PostgreSQL Database

```bash
sudo -u postgres psql
```

```sql
CREATE USER rims_user WITH PASSWORD 'your_secure_password';
CREATE DATABASE rims_db OWNER rims_user;
GRANT ALL PRIVILEGES ON DATABASE rims_db TO rims_user;
\q
```

Run migrations:

```bash
cd /var/www/rims-backend
source venv/bin/activate
alembic upgrade head
```

### 6. Create Systemd Service

Create `/etc/systemd/system/rims-backend.service`:

```ini
[Unit]
Description=RIMS Backend API (FastAPI)
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/var/www/rims-backend
EnvironmentFile=/var/www/rims-backend/.env
ExecStart=/var/www/rims-backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4
Restart=on-failure
RestartSec=10

# Security
NoNewPrivileges=true
PrivateTmp=true

# Logging
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Fix permissions and enable service:

```bash
sudo chown -R www-data:www-data /var/www/rims-backend
sudo chmod 600 /var/www/rims-backend/.env

sudo systemctl daemon-reload
sudo systemctl enable rims-backend
sudo systemctl start rims-backend
sudo systemctl status rims-backend
```

### 7. Configure Caddy

Add to `/etc/caddy/Caddyfile`:

```caddyfile
api.rims.r-dev.asia {
    # Enable compression
    encode gzip zstd

    # Reverse proxy to FastAPI
    reverse_proxy localhost:8000 {
        # Health check
        health_uri /health
        health_interval 30s
        
        # Headers
        header_up Host {host}
        header_up X-Real-IP {remote}
        header_up X-Forwarded-For {remote}
        header_up X-Forwarded-Proto {scheme}
        
        # Disable buffering for SSE
        flush_interval -1
    }

    # Security headers
    header {
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        X-XSS-Protection "1; mode=block"
        Referrer-Policy strict-origin-when-cross-origin
        -Server
    }

    # Logs
    log {
        output file /var/log/caddy/rims-backend.log
        format json
    }
}
```

Reload Caddy:

```bash
sudo mkdir -p /var/log/caddy
sudo systemctl reload caddy
```

### 8. Verify Deployment

```bash
# Check service status
sudo systemctl status rims-backend

# Check logs
sudo journalctl -u rims-backend -f

# Test endpoints
curl https://api.rims.r-dev.asia/health
curl https://api.rims.r-dev.asia/docs
```

### 9. Create Admin User

Use the installation wizard (recommended):

```bash
cd /var/www/rims-backend
source venv/bin/activate
python install.py
```

It will prompt you to create an admin user and will set `role="admin"`.

### Environment Variables Reference

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `DATABASE_URL` | Yes | PostgreSQL connection string | `postgresql+asyncpg://user:pass@localhost:5432/db` |
| `SECRET_KEY` | Yes | JWT signing key (min 32 chars) | `your-super-secret-key` |
| `ALLOWED_ORIGINS` | No | CORS origins (comma-separated) | `https://rims.r-dev.asia` |
| `JWT_ALGORITHM` | No | JWT algorithm | `HS256` |
| `JWT_EXPIRATION_HOURS` | No | Token expiry | `24` |
| `DEBUG` | No | Enable debug mode | `false` |

### Troubleshooting

**502 Bad Gateway**
```bash
sudo systemctl status rims-backend
curl localhost:8000/health
```

**Database Connection Error**
```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Test connection
sudo -u postgres psql -c "\l"
```

**Permission Denied**
```bash
sudo chown -R www-data:www-data /var/www/rims-backend
sudo chmod 600 /var/www/rims-backend/.env
```

**Migration Errors**
```bash
cd /var/www/rims-backend
source venv/bin/activate
alembic current  # Check current revision
alembic history  # View migration history
alembic upgrade head  # Apply pending migrations
```
