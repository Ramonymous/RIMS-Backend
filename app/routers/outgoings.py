"""Outgoing goods issue (Outgoing) management routes."""

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.deps import CurrentUser, require_permission
from app.models import Outgoing, OutgoingItem, Part, PartMovement
from app.schemas import (
    DocumentStatus,
    OutgoingCreate,
    OutgoingResponse,
    OutgoingUpdate,
    PaginatedResponse,
)

router = APIRouter(prefix="/outgoings", tags=["outgoings"])

# Type alias for database dependency
DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=PaginatedResponse[OutgoingResponse], dependencies=[Depends(require_permission("outgoings.view"))])
async def list_outgoings(
    db: DB,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    status_filter: DocumentStatus | None = Query(default=None),
    pending_gi: bool = Query(default=False),
    doc_number: str | None = Query(default=None),
) -> PaginatedResponse[OutgoingResponse]:
    """
    List all outgoings with optional filtering and pagination.
    
    status_filter options: draft, completed, cancelled
    pending_gi=true to get outgoings awaiting GI confirmation
    """
    base_query = (
        select(Outgoing)
        .where(Outgoing.deleted_at.is_(None))
    )

    if status_filter:
        base_query = base_query.where(Outgoing.status == status_filter.value)

    if pending_gi:
        base_query = base_query.where(
            and_(Outgoing.status == DocumentStatus.COMPLETED.value, Outgoing.is_gi.is_(False))
        )

    if doc_number:
        base_query = base_query.where(Outgoing.doc_number.icontains(doc_number))

    # Count total
    count_stmt = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Fetch page with eager loading
    offset = (page - 1) * limit
    stmt = (
        base_query
        .options(selectinload(Outgoing.items))
        .order_by(Outgoing.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    outgoings = result.scalars().all()

    return PaginatedResponse[OutgoingResponse](
        items=[OutgoingResponse.model_validate(o) for o in outgoings],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/{outgoing_id}", response_model=OutgoingResponse, dependencies=[Depends(require_permission("outgoings.view"))])
async def get_outgoing(
    outgoing_id: UUID,
    db: DB,
    current_user: CurrentUser,
) -> OutgoingResponse:
    """Get outgoing with nested items."""
    stmt = (
        select(Outgoing)
        .where(and_(Outgoing.id == outgoing_id, Outgoing.deleted_at.is_(None)))
        .options(selectinload(Outgoing.items))
    )
    result = await db.execute(stmt)
    outgoing = result.scalar_one_or_none()

    if not outgoing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Outgoing not found"
        )

    return OutgoingResponse.model_validate(outgoing)


@router.post("", response_model=OutgoingResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("outgoings.create"))])
async def create_outgoing(
    request: OutgoingCreate,
    db: DB,
    current_user: CurrentUser,
) -> OutgoingResponse:
    """Create a new outgoing in draft status."""
    outgoing = Outgoing(
        doc_number=request.doc_number,
        issued_by=request.issued_by,
        issued_at=request.issued_at,
        notes=request.notes,
        status=DocumentStatus.DRAFT.value,
    )

    # Add nested items
    for item_data in request.items:
        item = OutgoingItem(part_id=item_data.part_id, qty=item_data.qty)
        outgoing.items.append(item)

    db.add(outgoing)
    await db.commit()
    
    # Reload with items relationship
    stmt = (
        select(Outgoing)
        .where(Outgoing.id == outgoing.id)
        .options(selectinload(Outgoing.items))
    )
    result = await db.execute(stmt)
    return OutgoingResponse.model_validate(result.scalar_one())


@router.put("/{outgoing_id}", response_model=OutgoingResponse, dependencies=[Depends(require_permission("outgoings.update"))])
async def update_outgoing(
    outgoing_id: UUID,
    request: OutgoingUpdate,
    db: DB,
    current_user: CurrentUser,
) -> OutgoingResponse:
    """Update an outgoing (only if is_editable)."""
    stmt = (
        select(Outgoing)
        .where(and_(Outgoing.id == outgoing_id, Outgoing.deleted_at.is_(None)))
        .options(selectinload(Outgoing.items))
    )
    result = await db.execute(stmt)
    outgoing = result.scalar_one_or_none()

    if not outgoing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Outgoing not found"
        )

    if not outgoing.is_editable():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Outgoing is not editable (already confirmed as GI or cancelled)",
        )

    # Update scalar fields
    if request.doc_number is not None:
        outgoing.doc_number = request.doc_number
    if request.notes is not None:
        outgoing.notes = request.notes

    # Update nested items if provided
    if request.items is not None:
        outgoing.items.clear()
        for item_data in request.items:
            item = OutgoingItem(part_id=item_data.part_id, qty=item_data.qty)
            outgoing.items.append(item)

    await db.commit()
    
    stmt = (
        select(Outgoing)
        .where(Outgoing.id == outgoing.id)
        .options(selectinload(Outgoing.items))
    )
    result = await db.execute(stmt)
    return OutgoingResponse.model_validate(result.scalar_one())


@router.delete("/{outgoing_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("outgoings.delete"))])
async def delete_outgoing(
    outgoing_id: UUID,
    db: DB,
    current_user: CurrentUser,
) -> None:
    """Soft-delete an outgoing."""
    stmt = select(Outgoing).where(
        and_(Outgoing.id == outgoing_id, Outgoing.deleted_at.is_(None))
    )
    result = await db.execute(stmt)
    outgoing = result.scalar_one_or_none()

    if not outgoing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Outgoing not found"
        )

    outgoing.deleted_at = datetime.now(timezone.utc)
    await db.commit()


@router.put("/{outgoing_id}/complete", response_model=OutgoingResponse, dependencies=[Depends(require_permission("outgoings.complete"))])
async def complete_outgoing(
    outgoing_id: UUID,
    db: DB,
    current_user: CurrentUser,
) -> OutgoingResponse:
    """
    Complete an outgoing (draft → completed).
    
    Validates sufficient stock, creates PartMovements, and updates part stock with row-level locking.
    """
    stmt = (
        select(Outgoing)
        .where(and_(Outgoing.id == outgoing_id, Outgoing.deleted_at.is_(None)))
        .options(selectinload(Outgoing.items))
    )
    result = await db.execute(stmt)
    outgoing = result.scalar_one_or_none()

    if not outgoing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Outgoing not found"
        )

    if outgoing.status != DocumentStatus.DRAFT.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Outgoing status is {outgoing.status}, cannot complete",
        )

    # Batch fetch all parts with row-level locking (SELECT FOR UPDATE)
    part_ids = [item.part_id for item in outgoing.items]
    parts_stmt = select(Part).where(Part.id.in_(part_ids)).with_for_update()
    parts_result = await db.execute(parts_stmt)
    parts_map = {part.id: part for part in parts_result.scalars().all()}

    # Validate sufficient stock before making any changes
    for item in outgoing.items:
        part = parts_map[item.part_id]
        if part.stock < item.qty:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Insufficient stock for part {part.part_number} (available: {part.stock}, requested: {item.qty})",
            )

    # Process each item and create movements
    for item in outgoing.items:
        part = parts_map[item.part_id]
        stock_before = part.stock
        part.stock -= item.qty

        movement = PartMovement(
            part_id=item.part_id,
            stock_before=stock_before,
            type="out",
            qty=item.qty,
            stock_after=part.stock,
            reference_type="Outgoings",
            reference_id=outgoing.id,
        )
        db.add(movement)

    outgoing.status = DocumentStatus.COMPLETED.value
    await db.commit()
    
    stmt = (
        select(Outgoing)
        .where(Outgoing.id == outgoing.id)
        .options(selectinload(Outgoing.items))
    )
    result = await db.execute(stmt)
    return OutgoingResponse.model_validate(result.scalar_one())


@router.put("/{outgoing_id}/cancel", response_model=OutgoingResponse, dependencies=[Depends(require_permission("outgoings.cancel"))])
async def cancel_outgoing(
    outgoing_id: UUID,
    db: DB,
    current_user: CurrentUser,
) -> OutgoingResponse:
    """Cancel an outgoing (transitions status → cancelled)."""
    stmt = (
        select(Outgoing)
        .where(and_(Outgoing.id == outgoing_id, Outgoing.deleted_at.is_(None)))
        .options(selectinload(Outgoing.items))
    )
    result = await db.execute(stmt)
    outgoing = result.scalar_one_or_none()

    if not outgoing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Outgoing not found"
        )

    outgoing.status = DocumentStatus.CANCELLED.value
    await db.commit()
    
    stmt = (
        select(Outgoing)
        .where(Outgoing.id == outgoing.id)
        .options(selectinload(Outgoing.items))
    )
    result = await db.execute(stmt)
    return OutgoingResponse.model_validate(result.scalar_one())


@router.put("/{outgoing_id}/confirm-gi", response_model=OutgoingResponse, dependencies=[Depends(require_permission("outgoings.confirm_gi"))])
async def confirm_gi(
    outgoing_id: UUID,
    db: DB,
    current_user: CurrentUser,
) -> OutgoingResponse:
    """Confirm outgoing as Goods Issue (GI)."""
    stmt = (
        select(Outgoing)
        .where(and_(Outgoing.id == outgoing_id, Outgoing.deleted_at.is_(None)))
        .options(selectinload(Outgoing.items))
    )
    result = await db.execute(stmt)
    outgoing = result.scalar_one_or_none()

    if not outgoing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Outgoing not found"
        )

    if not outgoing.can_be_gi_confirmed():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Outgoing cannot be confirmed as GI (must be completed and not yet confirmed)",
        )

    outgoing.is_gi = True
    await db.commit()
    
    stmt = (
        select(Outgoing)
        .where(Outgoing.id == outgoing.id)
        .options(selectinload(Outgoing.items))
    )
    result = await db.execute(stmt)
    return OutgoingResponse.model_validate(result.scalar_one())
