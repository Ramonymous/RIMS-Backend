"""Incoming goods receipt (Receiving) management routes."""

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.deps import CurrentUser, require_permission
from app.models import Part, PartMovement, Receiving, ReceivingItem
from app.schemas import (
    DocumentStatus,
    PaginatedResponse,
    ReceivingCreate,
    ReceivingResponse,
    ReceivingUpdate,
)

router = APIRouter(prefix="/receivings", tags=["receivings"])

# Type alias for database dependency
DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=PaginatedResponse[ReceivingResponse], dependencies=[Depends(require_permission("receivings.view"))])
async def list_receivings(
    db: DB,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    status_filter: DocumentStatus | None = Query(default=None),
    pending_gr: bool = Query(default=False),
    doc_number: str | None = Query(default=None),
) -> PaginatedResponse[ReceivingResponse]:
    """
    List all receivings with optional filtering and pagination.
    
    status_filter options: draft, completed, cancelled
    pending_gr=true to get receivings awaiting GR confirmation
    """
    filters = [Receiving.deleted_at.is_(None)]

    if status_filter:
        filters.append(Receiving.status == status_filter.value)

    if pending_gr:
        filters.append(and_(Receiving.status == DocumentStatus.COMPLETED.value, Receiving.is_gr.is_(False)))

    if doc_number:
        filters.append(Receiving.doc_number.icontains(doc_number))

    # Count total
    count_stmt = select(func.count()).select_from(Receiving).where(*filters)
    total = int((await db.execute(count_stmt)).scalar() or 0)

    # Fetch page with eager loading
    offset = (page - 1) * limit
    stmt = (
        select(Receiving)
        .where(*filters)
        .options(selectinload(Receiving.items))
        .order_by(Receiving.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    receivings = result.scalars().all()

    return PaginatedResponse[ReceivingResponse](
        items=[ReceivingResponse.model_validate(r) for r in receivings],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/{receiving_id}", response_model=ReceivingResponse, dependencies=[Depends(require_permission("receivings.view"))])
async def get_receiving(
    receiving_id: UUID,
    db: DB,
    current_user: CurrentUser,
) -> ReceivingResponse:
    """Get receiving with nested items."""
    stmt = (
        select(Receiving)
        .where(and_(Receiving.id == receiving_id, Receiving.deleted_at.is_(None)))
        .options(selectinload(Receiving.items))
    )
    result = await db.execute(stmt)
    receiving = result.scalar_one_or_none()

    if not receiving:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Receiving not found"
        )

    return ReceivingResponse.model_validate(receiving)


@router.post("", response_model=ReceivingResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("receivings.create"))])
async def create_receiving(
    request: ReceivingCreate,
    db: DB,
    current_user: CurrentUser,
) -> ReceivingResponse:
    """Create a new receiving in draft status."""
    receiving = Receiving(
        doc_number=request.doc_number,
        received_by=request.received_by,
        received_at=request.received_at,
        notes=request.notes,
        status=DocumentStatus.DRAFT.value,
    )

    # Add nested items
    for item_data in request.items:
        item = ReceivingItem(part_id=item_data.part_id, qty=item_data.qty)
        receiving.items.append(item)

    db.add(receiving)
    await db.commit()
    
    # Reload with items relationship
    stmt = (
        select(Receiving)
        .where(Receiving.id == receiving.id)
        .options(selectinload(Receiving.items))
    )
    result = await db.execute(stmt)
    return ReceivingResponse.model_validate(result.scalar_one())


@router.put("/{receiving_id}", response_model=ReceivingResponse, dependencies=[Depends(require_permission("receivings.update"))])
async def update_receiving(
    receiving_id: UUID,
    request: ReceivingUpdate,
    db: DB,
    current_user: CurrentUser,
) -> ReceivingResponse:
    """Update a receiving (only if is_editable)."""
    stmt = (
        select(Receiving)
        .where(and_(Receiving.id == receiving_id, Receiving.deleted_at.is_(None)))
        .options(selectinload(Receiving.items))
    )
    result = await db.execute(stmt)
    receiving = result.scalar_one_or_none()

    if not receiving:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Receiving not found"
        )

    if not receiving.is_editable():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Receiving is not editable (already confirmed as GR or cancelled)",
        )

    # Update scalar fields
    if request.doc_number is not None:
        receiving.doc_number = request.doc_number
    if request.notes is not None:
        receiving.notes = request.notes

    # Update nested items if provided
    if request.items is not None:
        receiving.items.clear()
        for item_data in request.items:
            item = ReceivingItem(part_id=item_data.part_id, qty=item_data.qty)
            receiving.items.append(item)

    await db.commit()
    
    stmt = (
        select(Receiving)
        .where(Receiving.id == receiving.id)
        .options(selectinload(Receiving.items))
    )
    result = await db.execute(stmt)
    return ReceivingResponse.model_validate(result.scalar_one())


@router.delete("/{receiving_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("receivings.delete"))])
async def delete_receiving(
    receiving_id: UUID,
    db: DB,
    current_user: CurrentUser,
) -> None:
    """Soft-delete a receiving."""
    stmt = select(Receiving).where(
        and_(Receiving.id == receiving_id, Receiving.deleted_at.is_(None))
    )
    result = await db.execute(stmt)
    receiving = result.scalar_one_or_none()

    if not receiving:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Receiving not found"
        )

    receiving.deleted_at = datetime.now(timezone.utc)
    await db.commit()


@router.put("/{receiving_id}/complete", response_model=ReceivingResponse, dependencies=[Depends(require_permission("receivings.complete"))])
async def complete_receiving(
    receiving_id: UUID,
    db: DB,
    current_user: CurrentUser,
) -> ReceivingResponse:
    """
    Complete a receiving (draft → completed).
    
    Creates PartMovements for all items and updates part stock with row-level locking.
    """
    stmt = (
        select(Receiving)
        .where(and_(Receiving.id == receiving_id, Receiving.deleted_at.is_(None)))
        .options(selectinload(Receiving.items))
    )
    result = await db.execute(stmt)
    receiving = result.scalar_one_or_none()

    if not receiving:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Receiving not found"
        )

    if receiving.status != DocumentStatus.DRAFT.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Receiving status is {receiving.status}, cannot complete",
        )

    # Batch fetch all parts with row-level locking (SELECT FOR UPDATE)
    part_ids = [item.part_id for item in receiving.items]
    parts_stmt = select(Part).where(Part.id.in_(part_ids)).with_for_update()
    parts_result = await db.execute(parts_stmt)
    parts_map = {part.id: part for part in parts_result.scalars().all()}

    # Process each item and create movements
    for item in receiving.items:
        part = parts_map[item.part_id]
        stock_before = part.stock
        part.stock += item.qty

        movement = PartMovement(
            part_id=item.part_id,
            stock_before=stock_before,
            type="in",
            qty=item.qty,
            stock_after=part.stock,
            reference_type="Receivings",
            reference_id=receiving.id,
        )
        db.add(movement)

    receiving.status = DocumentStatus.COMPLETED.value
    await db.commit()
    
    stmt = (
        select(Receiving)
        .where(Receiving.id == receiving.id)
        .options(selectinload(Receiving.items))
    )
    result = await db.execute(stmt)
    return ReceivingResponse.model_validate(result.scalar_one())


@router.put("/{receiving_id}/cancel", response_model=ReceivingResponse, dependencies=[Depends(require_permission("receivings.cancel"))])
async def cancel_receiving(
    receiving_id: UUID,
    db: DB,
    current_user: CurrentUser,
) -> ReceivingResponse:
    """Cancel a receiving (transitions status → cancelled)."""
    stmt = (
        select(Receiving)
        .where(and_(Receiving.id == receiving_id, Receiving.deleted_at.is_(None)))
        .options(selectinload(Receiving.items))
    )
    result = await db.execute(stmt)
    receiving = result.scalar_one_or_none()

    if not receiving:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Receiving not found"
        )

    receiving.status = DocumentStatus.CANCELLED.value
    await db.commit()
    
    stmt = (
        select(Receiving)
        .where(Receiving.id == receiving.id)
        .options(selectinload(Receiving.items))
    )
    result = await db.execute(stmt)
    return ReceivingResponse.model_validate(result.scalar_one())


@router.put("/{receiving_id}/confirm-gr", response_model=ReceivingResponse, dependencies=[Depends(require_permission("receivings.confirm_gr"))])
async def confirm_gr(
    receiving_id: UUID,
    db: DB,
    current_user: CurrentUser,
) -> ReceivingResponse:
    """Confirm receiving as Goods Receipt (GR)."""
    stmt = (
        select(Receiving)
        .where(and_(Receiving.id == receiving_id, Receiving.deleted_at.is_(None)))
        .options(selectinload(Receiving.items))
    )
    result = await db.execute(stmt)
    receiving = result.scalar_one_or_none()

    if not receiving:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Receiving not found"
        )

    if not receiving.can_be_gr_confirmed():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Receiving cannot be confirmed as GR (must be completed and not yet confirmed)",
        )

    receiving.is_gr = True
    await db.commit()
    
    stmt = (
        select(Receiving)
        .where(Receiving.id == receiving.id)
        .options(selectinload(Receiving.items))
    )
    result = await db.execute(stmt)
    return ReceivingResponse.model_validate(result.scalar_one())
