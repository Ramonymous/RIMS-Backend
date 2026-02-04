# ProjectRIMS Backend - Agent Instructions

This is the backend for ProjectRIMS, a FastAPI-based inventory management system.

## Tech Stack

- **Framework**: FastAPI
- **Database**: PostgreSQL with SQLAlchemy (async)
- **ORM**: SQLAlchemy 2.0 with async support
- **Migrations**: Alembic
- **Authentication**: JWT tokens via python-jose
- **Password Hashing**: bcrypt via passlib

## Project Structure

```
backend/
├── app/
│   ├── main.py          # FastAPI application entry point
│   ├── core/            # Core configuration, database, security
│   ├── models/          # SQLAlchemy ORM models
│   ├── routers/         # API route handlers
│   └── schemas/         # Pydantic schemas for request/response
├── migrations/          # Alembic database migrations
├── tests/               # Test files
├── venv/                # Python virtual environment
├── requirements.txt     # Python dependencies
└── alembic.ini          # Alembic configuration
```

## Development Commands

### Activate Virtual Environment
```powershell
.\venv\Scripts\Activate.ps1
```

### Start Development Server
```powershell
uvicorn app.main:app --reload --port 8000
```

### Database Migrations
```powershell
# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

## API Documentation

When the server is running:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## Coding Guidelines

1. **Async First**: All database operations should use async/await
2. **Type Hints**: Always use type hints for function parameters and returns
3. **Pydantic Models**: Use Pydantic schemas for all request/response validation
4. **Dependency Injection**: Use FastAPI's Depends() for shared logic
5. **Error Handling**: Use HTTPException with appropriate status codes
6. **Logging**: Use the configured logger for important operations

## Environment Variables

Configuration is managed via `.env` file. See `.env.example` for required variables.
