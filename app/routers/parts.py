"""Parts inventory management routes."""

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser
from app.models import Part, PartMovement
from app.schemas import (
    PaginatedResponse,
    PartCreate,
    PartMovementResponse,
    PartResponse,
    PartUpdate,
    StockStatusFilter,
)

router = APIRouter(prefix="/parts", tags=["parts"])

# Type alias for database dependency
DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=PaginatedResponse[PartResponse])
async def list_parts(
    db: DB,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None),
    status_filter: StockStatusFilter | None = Query(default=None),
) -> PaginatedResponse[PartResponse]:
    """
    List all parts with optional filtering and pagination.
    
    status_filter options: active, inactive, in_stock, low_stock, out_of_stock
    """
    # Base query
    base_query = select(Part).where(Part.deleted_at.is_(None))

    # Apply search filter
    if search:
        base_query = base_query.where(
            (Part.part_number.icontains(search))
            | (Part.part_name.icontains(search))
            | (Part.customer_code.icontains(search))
            | (Part.supplier_code.icontains(search))
            | (Part.model.icontains(search))
        )

    # Apply status filter in SQL (not Python!)
    if status_filter == StockStatusFilter.ACTIVE:
        base_query = base_query.where(Part.is_active.is_(True))
    elif status_filter == StockStatusFilter.INACTIVE:
        base_query = base_query.where(Part.is_active.is_(False))
    elif status_filter == StockStatusFilter.IN_STOCK:
        base_query = base_query.where(Part.stock > 10)
    elif status_filter == StockStatusFilter.LOW_STOCK:
        base_query = base_query.where(and_(Part.stock > 0, Part.stock <= 10))
    elif status_filter == StockStatusFilter.OUT_OF_STOCK:
        base_query = base_query.where(Part.stock <= 0)

    # Count total matching records
    count_stmt = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Fetch page
    offset = (page - 1) * limit
    stmt = base_query.offset(offset).limit(limit)
    result = await db.execute(stmt)
    parts = result.scalars().all()

    return PaginatedResponse[PartResponse](
        items=[PartResponse.model_validate(p) for p in parts],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/{part_id}", response_model=PartResponse)
async def get_part(
    part_id: UUID,
    db: DB,
    current_user: CurrentUser,
) -> PartResponse:
    """Get part by ID."""
    stmt = select(Part).where(and_(Part.id == part_id, Part.deleted_at.is_(None)))
    result = await db.execute(stmt)
    part = result.scalar_one_or_none()

    if not part:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")

    return PartResponse.model_validate(part)


@router.post("", response_model=PartResponse, status_code=status.HTTP_201_CREATED)
async def create_part(
    request: PartCreate,
    db: DB,
    current_user: CurrentUser,
) -> PartResponse:
    """Create a new part."""
    part = Part(**request.model_dump())
    db.add(part)
    await db.commit()
    await db.refresh(part)
    return PartResponse.model_validate(part)


@router.put("/{part_id}", response_model=PartResponse)
async def update_part(
    part_id: UUID,
    request: PartUpdate,
    db: DB,
    current_user: CurrentUser,
) -> PartResponse:
    """Update a part."""
    stmt = select(Part).where(and_(Part.id == part_id, Part.deleted_at.is_(None)))
    result = await db.execute(stmt)
    part = result.scalar_one_or_none()

    if not part:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")

    # Update fields if provided
    update_data = request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(part, key, value)

    await db.commit()
    await db.refresh(part)
    return PartResponse.model_validate(part)


@router.delete("/{part_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_part(
    part_id: UUID,
    db: DB,
    current_user: CurrentUser,
) -> None:
    """Soft-delete a part."""
    stmt = select(Part).where(and_(Part.id == part_id, Part.deleted_at.is_(None)))
    result = await db.execute(stmt)
    part = result.scalar_one_or_none()

    if not part:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")

    part.deleted_at = datetime.now(timezone.utc)
    await db.commit()


@router.get("/{part_id}/movements", response_model=PaginatedResponse[PartMovementResponse])
async def get_part_movements(
    part_id: UUID,
    db: DB,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> PaginatedResponse[PartMovementResponse]:
    """Get movement history for a part with pagination."""
    # Verify part exists
    stmt = select(Part).where(and_(Part.id == part_id, Part.deleted_at.is_(None)))
    result = await db.execute(stmt)
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")

    # Count total movements
    count_stmt = select(func.count()).select_from(PartMovement).where(PartMovement.part_id == part_id)
    total = (await db.execute(count_stmt)).scalar() or 0

    # Get movements with pagination
    offset = (page - 1) * limit
    stmt = (
        select(PartMovement)
        .where(PartMovement.part_id == part_id)
        .order_by(PartMovement.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    movements = result.scalars().all()

    return PaginatedResponse[PartMovementResponse](
        items=[PartMovementResponse.model_validate(m) for m in movements],
        total=total,
        page=page,
        limit=limit,
    )
