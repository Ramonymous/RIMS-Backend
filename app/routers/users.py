"""User management routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, require_permission
from app.core.security import hash_password
from app.models import User
from app.schemas import PaginatedResponse, UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])

# Type alias for database dependency
DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=PaginatedResponse[UserResponse])
async def list_users(
    db: DB,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> PaginatedResponse[UserResponse]:
    """List all users with pagination."""
    # Count total
    count_stmt = select(func.count()).select_from(User)
    total = (await db.execute(count_stmt)).scalar() or 0
    
    # Fetch page
    offset = (page - 1) * limit
    stmt = select(User).offset(offset).limit(limit)
    result = await db.execute(stmt)
    users = result.scalars().all()
    
    return PaginatedResponse[UserResponse](
        items=[UserResponse.model_validate(u) for u in users],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: CurrentUser) -> UserResponse:
    """Get current authenticated user."""
    return UserResponse.model_validate(current_user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    db: DB,
    current_user: CurrentUser,
) -> UserResponse:
    """Get user by ID."""
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return UserResponse.model_validate(user)


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def create_user(request: UserCreate, db: DB) -> UserResponse:
    """Create a new user. Requires manage_users permission."""
    # Check for duplicate email
    existing_stmt = select(User).where(User.email == request.email)
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    
    user = User(
        name=request.name,
        email=request.email,
        password=hash_password(request.password),
        permissions=request.permissions,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.put(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def update_user(
    user_id: UUID,
    request: UserUpdate,
    db: DB,
) -> UserResponse:
    """Update a user. Requires manage_users permission."""
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Check email uniqueness if changing email
    if request.email is not None and request.email != user.email:
        existing_stmt = select(User).where(User.email == request.email)
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )
        user.email = request.email

    if request.name is not None:
        user.name = request.name
    if request.permissions is not None:
        user.permissions = request.permissions

    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def delete_user(user_id: UUID, db: DB, current_user: CurrentUser) -> None:
    """Delete a user. Requires manage_users permission."""
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete yourself",
        )
    
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await db.delete(user)
    await db.commit()
