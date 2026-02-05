"""Parts inventory management routes."""

from datetime import datetime, timezone
from typing import Annotated
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

# Redis Configuration - Menggunakan 127.0.0.1 sesuai snippet terbaru
REDIS_URL = "redis://127.0.0.1:6379/0"
# Explicit type annotation untuk menghindari "unknown type" warning
redis_client: redis.Redis = redis.Redis.from_url(REDIS_URL, decode_responses=True) # type: ignore

GATEWAY_API_KEY = "your-secret-gateway-key-here"  # Disarankan simpan di environment variable
QUEUE_KEY = "rims:pick_queue"

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
    """Memicu proses picking dan memasukkan part ke antrean Redis."""
    stmt = select(Part).where(
        and_(Part.part_number == payload.part_number, Part.deleted_at.is_(None))
    )
    result = await db.execute(stmt)
    part = result.scalar_one_or_none()

    if not part:
        logger.warning(f"Pick attempt for non-existent part: {payload.part_number}")
        raise HTTPException(status_code=404, detail="Part tidak ditemukan")

    # Tambahkan ke antrean Redis
    queue_len = await redis_client.rpush(QUEUE_KEY, part.part_number) # pyright: ignore[reportGeneralTypeIssues, reportUnknownVariableType]
    logger.info(f"Part {part.part_number} pushed to queue. Current queue length: {queue_len}")
    
    return PartResponse.model_validate(part)

@router.get("/queue/next", response_model=None)
async def get_next_command(
    x_api_key: str = Header(...)
) -> dict[str, str] | Response:
    """Endpoint untuk Gateway menarik perintah selanjutnya (Atomic Pull)."""
    if x_api_key != GATEWAY_API_KEY:
        logger.warning("Unauthorized access attempt to queue/next")
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    # Ambil item dari sisi kiri (FIFO)
    next_part = await redis_client.lpop(QUEUE_KEY) # type: ignore

    if not next_part:
        # Gunakan debug agar log tidak penuh saat tidak ada aktivitas
        return Response(status_code=204)

    logger.info(f"Gateway pulled command: {next_part}")
    return {"part_number": str(next_part)} # type: ignore

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