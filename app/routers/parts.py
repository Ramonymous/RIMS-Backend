"""Parts inventory management routes."""

from datetime import datetime, timezone, date, time
from typing import Annotated, List
from uuid import UUID
import redis.asyncio as redis
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status, Response, Header
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, require_permission
from app.models import Part, PartMovement
from app.schemas import (
    PaginatedResponse,
    PartCreate,
    PartMovementResponse,
    PartResponse,
    PickRequest,
    PartUpdate,
    StockStatusFilter,
)

# Setup logger
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parts", tags=["parts"])

# Type alias for database dependency
DB = Annotated[AsyncSession, Depends(get_db)]

# Redis Configuration
REDIS_URL = "redis://127.0.0.1:6379/0"
redis_client: redis.Redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)  # type: ignore

GATEWAY_API_KEY = "your-secret-gateway-key-here"
QUEUE_KEY = "rims:pick_queue"

# Google Sheets sync token (store in environment variables in production)
GOOGLE_SHEETS_SYNC_TOKEN = "your-google-sheets-sync-token-here"


# Custom response models for Google Sheets sync
from pydantic import BaseModel


class MovementSyncItem(BaseModel):
    """Simplified movement data for Google Sheets sync."""
    part_number: str
    date: str  # YYYY-MM-DD format
    time: str  # HH:MM:SS format
    type: str  # IN or OUT
    qty: int


class MovementSyncResponse(BaseModel):
    """Response model for Google Sheets sync."""
    success: bool = True
    data: List[MovementSyncItem]
    total: int


class PingResponse(BaseModel):
    """Response model for ping endpoint."""
    success: bool
    message: str
    timestamp: str


@router.get("", response_model=PaginatedResponse[PartResponse], dependencies=[Depends(require_permission("parts.view"))])
async def list_parts(
    db: DB,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None),
    status_filter: StockStatusFilter | None = Query(default=None),
) -> PaginatedResponse[PartResponse]:
    """List all parts with optional filtering and pagination."""
    base_query = select(Part).where(Part.deleted_at.is_(None))

    if search:
        base_query = base_query.where(
            (Part.part_number.icontains(search))
            | (Part.part_name.icontains(search))
            | (Part.customer_code.icontains(search))
            | (Part.supplier_code.icontains(search))
            | (Part.model.icontains(search))
        )

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

    count_stmt = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

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


@router.post("/pick", response_model=PartResponse)
async def pick_part(
    payload: PickRequest,
    db: DB,
) -> PartResponse:
    """Trigger picking process and add part to Redis queue."""
    stmt = select(Part).where(
        and_(Part.part_number == payload.part_number, Part.deleted_at.is_(None))
    )
    result = await db.execute(stmt)
    part = result.scalar_one_or_none()

    if not part:
        logger.warning(f"Pick attempt for non-existent part: {payload.part_number}")
        raise HTTPException(status_code=404, detail="Part not found")

    # Add to Redis queue
    queue_len = await redis_client.rpush(QUEUE_KEY, part.part_number)  # pyright: ignore[reportGeneralTypeIssues, reportUnknownVariableType]
    logger.info(f"Part {part.part_number} pushed to queue. Current queue length: {queue_len}")
    
    return PartResponse.model_validate(part)


@router.get("/queue/next", response_model=None)
async def get_next_command(
    x_api_key: str = Header(...)
) -> dict[str, str] | Response:
    """Endpoint for Gateway to pull next command (Atomic Pull)."""
    if x_api_key != GATEWAY_API_KEY:
        logger.warning("Unauthorized access attempt to queue/next")
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    # Get item from left side (FIFO)
    next_part = await redis_client.lpop(QUEUE_KEY)  # type: ignore

    if not next_part:
        # Use debug so logs don't fill up when there's no activity
        return Response(status_code=204)

    logger.info(f"Gateway pulled command: {next_part}")
    return {"part_number": str(next_part)}  # type: ignore


@router.get("/{part_id}", response_model=PartResponse, dependencies=[Depends(require_permission("parts.view"))])
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


@router.post("", response_model=PartResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("parts.create"))])
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


@router.put("/{part_id}", response_model=PartResponse, dependencies=[Depends(require_permission("parts.update"))])
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

    update_data = request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(part, key, value)

    await db.commit()
    await db.refresh(part)
    return PartResponse.model_validate(part)


@router.delete("/{part_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("parts.delete"))])
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


@router.get("/{part_id}/movements", response_model=PaginatedResponse[PartMovementResponse], dependencies=[Depends(require_permission("parts.view"))])
async def get_part_movements(
    part_id: UUID,
    db: DB,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> PaginatedResponse[PartMovementResponse]:
    """Get movement history with pagination."""
    stmt = select(Part).where(and_(Part.id == part_id, Part.deleted_at.is_(None)))
    result = await db.execute(stmt)
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")

    count_stmt = select(func.count()).select_from(PartMovement).where(PartMovement.part_id == part_id)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

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


# =============================================
# GOOGLE SHEETS SYNC ENDPOINTS (SIMPLIFIED FORMAT)
# =============================================

@router.get("/movements/sync", response_model=MovementSyncResponse)
async def sync_movements_for_sheets(
    db: DB,
    start_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD)"),
    part_number: str | None = Query(default=None, description="Filter by part number"),
    movement_type: str | None = Query(default=None, description="Filter by movement type (IN/OUT)"),
    token: str = Query(..., description="API token for authentication"),
) -> MovementSyncResponse:
    """
    Special endpoint for Google Sheets sync with simplified authentication.
    Returns data in exact format needed for spreadsheet: part_number | date | time | type | qty
    """
    # Validate token
    if token != GOOGLE_SHEETS_SYNC_TOKEN:
        logger.warning(f"Invalid sync token attempt: {token}")
        raise HTTPException(status_code=401, detail="Invalid sync token")
    
    # Build query
    start_datetime = datetime.combine(start_date, time.min)
    end_datetime = datetime.combine(end_date, time.max)
    
    base_query = (
        select(PartMovement, Part.part_number)
        .join(Part, PartMovement.part_id == Part.id)
        .where(Part.deleted_at.is_(None))
        .where(PartMovement.created_at >= start_datetime)
        .where(PartMovement.created_at <= end_datetime)
    )
    
    # Apply additional filters if provided
    if part_number:
        base_query = base_query.where(Part.part_number.icontains(part_number))
    
    if movement_type:
        base_query = base_query.where(PartMovement.type == movement_type.lower())
    
    # Order by date/time
    stmt = (
        base_query
        .order_by(PartMovement.created_at.asc())  # Oldest first for chronological order
    )
    
    result = await db.execute(stmt)
    rows = result.all()
    
    # Format data for Google Sheets
    sync_data: List[MovementSyncItem] = []
    for movement, part_num in rows:
        created_at = movement.created_at
        
        # Format date and time
        date_str = created_at.strftime("%Y-%m-%d")
        time_str = created_at.strftime("%H:%M:%S")
        
        # Format type to uppercase (IN/OUT)
        movement_type_upper = movement.type.upper()
        
        sync_item = MovementSyncItem(
            part_number=part_num,
            date=date_str,
            time=time_str,
            type=movement_type_upper,
            qty=movement.qty
        )
        sync_data.append(sync_item)
    
    return MovementSyncResponse(
        success=True,
        data=sync_data,
        total=len(sync_data)
    )


@router.get("/sync/ping", response_model=PingResponse)
async def sync_ping(token: str = Query(..., description="API token for authentication")) -> PingResponse:
    """Simple ping endpoint to test Google Sheets connection."""
    if token != GOOGLE_SHEETS_SYNC_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid sync token")
    
    return PingResponse(
        success=True,
        message="Google Sheets sync API is working",
        timestamp=datetime.now(timezone.utc).isoformat()
    )