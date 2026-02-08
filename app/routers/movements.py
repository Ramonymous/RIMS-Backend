"""Movements router - API endpoints for stock movements."""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser
from app.models import PartMovement
from app.schemas import (
    MovementType,
    PaginatedResponse,
    PartMovementResponse,
    ReferenceType,
)

router = APIRouter(prefix="/movements", tags=["movements"])

# Type alias for database dependency
DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=PaginatedResponse[PartMovementResponse])
async def get_movements(
    db: DB,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    part_id: UUID | None = Query(default=None, description="Filter by part ID"),
    movement_type: MovementType | None = Query(default=None, alias="type", description="Filter by movement type"),
    reference_type: ReferenceType | None = Query(default=None, description="Filter by reference type"),
    start_date: date | None = Query(default=None, description="Filter by start date (YYYY-MM-DD)"),
    end_date: date | None = Query(default=None, description="Filter by end date (YYYY-MM-DD)"),
) -> PaginatedResponse[PartMovementResponse]:
    """
    Get all movements with optional filters and pagination.
    
    - **part_id**: Filter movements for a specific part
    - **type**: Filter by movement type ('in' for receiving, 'out' for outgoing)
    - **reference_type**: Filter by source document type ('Receivings' or 'Outgoings')
    - **start_date**: Only include movements on or after this date (strict YYYY-MM-DD format)
    - **end_date**: Only include movements on or before this date (strict YYYY-MM-DD format)
    """
    filters = []
    
    # Apply filters
    if part_id:
        filters.append(PartMovement.part_id == part_id)
    
    if movement_type:
        filters.append(PartMovement.type == movement_type.value)
    
    if reference_type:
        filters.append(PartMovement.reference_type == reference_type.value)
    
    if start_date:
        start_dt = datetime.combine(start_date, datetime.min.time())
        filters.append(PartMovement.created_at >= start_dt)
    
    if end_date:
        end_dt = datetime.combine(end_date, datetime.max.time())
        filters.append(PartMovement.created_at <= end_dt)
    
    # Count total
    count_stmt = select(func.count()).select_from(PartMovement)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = int((await db.execute(count_stmt)).scalar() or 0)
    
    # Order by most recent first and paginate
    offset = (page - 1) * limit
    stmt = select(PartMovement)
    if filters:
        stmt = stmt.where(*filters)
    stmt = stmt.order_by(PartMovement.created_at.desc()).offset(offset).limit(limit)
    
    result = await db.execute(stmt)
    movements = result.scalars().all()
    
    return PaginatedResponse[PartMovementResponse](
        items=[PartMovementResponse.model_validate(m) for m in movements],
        total=total,
        page=page,
        limit=limit,
    )
