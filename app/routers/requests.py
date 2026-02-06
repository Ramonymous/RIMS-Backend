"""Parts request management routes."""

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.deps import CurrentUser
from app.core.events import broadcaster
from app.models import Part, Request, RequestList, Outgoing, OutgoingItem, PartMovement
from app.schemas import (
    DocumentStatus,
    PaginatedResponse,
    RequestCreate,
    RequestResponse,
    RequestUpdate,
    RequestListResponse,
)

# Type alias for database dependency
DB = Annotated[AsyncSession, Depends(get_db)]

class ItemDataDict(TypedDict):
    """Type definition for item broadcast data."""
    id: str
    part: dict[str, Any]
    qty: int
    is_urgent: bool
    is_supplied: bool
    request: dict[str, Any]

router = APIRouter(prefix="/requests", tags=["requests"])


# --- New: Pick/Check a request item ---

from pydantic import BaseModel

class PickRequestBody(BaseModel):
    item_id: UUID

@router.post("/pick", response_model=RequestListResponse)
async def pick_request_item(
    body: PickRequestBody,
    db: DB,
    current_user: CurrentUser,
):
    """Trigger a location check for a request item (e.g., lighting up an LED)."""
    # Permission: requests.locations
    if not current_user.has_permission("requests.locations"):
        raise HTTPException(status_code=403, detail="Permission denied: requests.locations")

    item_id = body.item_id
    # Find the request item with part information
    stmt = (
        select(RequestList)
        .where(RequestList.id == item_id)
    )
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    
    if not item:
        raise HTTPException(status_code=404, detail="Request item not found")

    # Fetch part details
    part_stmt = select(Part).where(Part.id == item.part_id)
    part_result = await db.execute(part_stmt)
    part = part_result.scalar_one_or_none()

    # Compose response with part details
    item_dict = item.__dict__.copy()
    if part:
        item_dict['part'] = {
            'id': str(part.id),
            'part_number': part.part_number,
            'part_name': part.part_name,
            'stock': part.stock,
            'address': part.address,
        }
    else:
        item_dict['part'] = None

    # Di sini biasanya ada logika untuk berkomunikasi dengan hardware/IoT
    # Untuk sekarang kita hanya mengembalikan status sukses
    return RequestListResponse.model_validate(item_dict)


@router.get("", response_model=PaginatedResponse[RequestResponse])
async def list_requests(
    db: DB,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    status_filter: DocumentStatus | None = Query(default=None),
    request_number: str | None = Query(default=None),
) -> PaginatedResponse[RequestResponse]:
    """List all requests with optional filtering and pagination."""
    # Permission: requests.view
    if not current_user.has_permission("requests.view"):
        raise HTTPException(status_code=403, detail="Permission denied: requests.view")
    
    base_query = select(Request).where(Request.deleted_at.is_(None))

    if status_filter:
        base_query = base_query.where(Request.status == status_filter.value)

    if request_number:
        base_query = base_query.where(Request.request_number.icontains(request_number))

    # Count total
    count_stmt = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Fetch page with eager loading
    offset = (page - 1) * limit
    stmt = (
        base_query
        .options(selectinload(Request.items), selectinload(Request.requested_by_user))
        .order_by(Request.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    requests = result.scalars().all()

    return PaginatedResponse[RequestResponse](
        items=[RequestResponse.model_validate(r) for r in requests],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/{request_id}", response_model=RequestResponse)
async def get_request(
    request_id: UUID,
    db: DB,
    current_user: CurrentUser,
) -> RequestResponse:
    """Get request with nested items."""
    # Permission: requests.view
    if not current_user.has_permission("requests.view"):
        raise HTTPException(status_code=403, detail="Permission denied: requests.view")
    
    stmt = (
        select(Request)
        .where(and_(Request.id == request_id, Request.deleted_at.is_(None)))
        .options(selectinload(Request.items), selectinload(Request.requested_by_user))
    )
    result = await db.execute(stmt)
    request_obj = result.scalar_one_or_none()

    if not request_obj:
        raise HTTPException(status_code=404, detail="Request not found")

    return RequestResponse.model_validate(request_obj)


@router.post("", response_model=RequestResponse, status_code=status.HTTP_201_CREATED)
async def create_request(
    request: RequestCreate,
    db: DB,
    current_user: CurrentUser,
) -> RequestResponse:
    """Create a new request in draft status."""
    # Permission: requests.create
    if not current_user.has_permission("requests.create"):
        raise HTTPException(status_code=403, detail="Permission denied: requests.create")
    
    request_obj = Request(
        request_number=request.request_number,
        requested_by=request.requested_by,
        requested_at=request.requested_at,
        destination=request.destination,
        notes=request.notes,
        status=DocumentStatus.DRAFT.value,
    )

    # Add nested items
    for item_data in request.items:
        item = RequestList(
            part_id=item_data.part_id,
            qty=item_data.qty,
            is_urgent=item_data.is_urgent,
        )
        request_obj.items.append(item)

    db.add(request_obj)
    await db.commit()
    
    # Reload with items and user relationship
    stmt = (
        select(Request)
        .where(Request.id == request_obj.id)
        .options(selectinload(Request.items), selectinload(Request.requested_by_user))
    )
    result = await db.execute(stmt)
    return RequestResponse.model_validate(result.scalar_one())


@router.put("/{request_id}", response_model=RequestResponse)
async def update_request(
    request_id: UUID,
    request: RequestUpdate,
    db: DB,
    current_user: CurrentUser,
) -> RequestResponse:
    """Update a request."""
    # Permission: requests.update
    if not current_user.has_permission("requests.update"):
        raise HTTPException(status_code=403, detail="Permission denied: requests.update")
    
    stmt = (
        select(Request)
        .where(and_(Request.id == request_id, Request.deleted_at.is_(None)))
        .options(selectinload(Request.items), selectinload(Request.requested_by_user))
    )
    result = await db.execute(stmt)
    request_obj = result.scalar_one_or_none()

    if not request_obj:
        raise HTTPException(status_code=404, detail="Request not found")

    # Update scalar fields
    if request.request_number is not None:
        request_obj.request_number = request.request_number
    if request.destination is not None:
        request_obj.destination = request.destination
    if request.notes is not None:
        request_obj.notes = request.notes

    # Update nested items if provided
    if request.items is not None:
        request_obj.items.clear()
        for item_data in request.items:
            item = RequestList(
                part_id=item_data.part_id,
                qty=item_data.qty,
                is_urgent=item_data.is_urgent,
            )
            request_obj.items.append(item)

    await db.commit()
    
    # Refresh to get updated data
    stmt = (
        select(Request)
        .where(Request.id == request_obj.id)
        .options(selectinload(Request.items), selectinload(Request.requested_by_user))
    )
    result = await db.execute(stmt)
    return RequestResponse.model_validate(result.scalar_one())


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_request(
    request_id: UUID,
    db: DB,
    current_user: CurrentUser,
) -> None:
    """Soft-delete a request."""
    # Permission: requests.delete
    if not current_user.has_permission("requests.delete"):
        raise HTTPException(status_code=403, detail="Permission denied: requests.delete")
    
    stmt = select(Request).where(
        and_(Request.id == request_id, Request.deleted_at.is_(None))
    )
    result = await db.execute(stmt)
    request_obj = result.scalar_one_or_none()

    if not request_obj:
        raise HTTPException(status_code=404, detail="Request not found")

    request_obj.deleted_at = datetime.now(timezone.utc)
    await db.commit()


@router.put("/{request_id}/complete", response_model=RequestResponse)
async def complete_request(
    request_id: UUID,
    db: DB,
    current_user: CurrentUser,
) -> RequestResponse:
    """Complete a request (transitions status → completed)."""
    # Permission: requests.complete
    if not current_user.has_permission("requests.complete"):
        raise HTTPException(status_code=403, detail="Permission denied: requests.complete")
    
    stmt = (
        select(Request)
        .where(and_(Request.id == request_id, Request.deleted_at.is_(None)))
        .options(selectinload(Request.items), selectinload(Request.requested_by_user))
    )
    result = await db.execute(stmt)
    request_obj = result.scalar_one_or_none()

    if not request_obj:
        raise HTTPException(status_code=404, detail="Request not found")

    if request_obj.status != DocumentStatus.DRAFT.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Request status is {request_obj.status}, cannot complete",
        )

    request_obj.status = DocumentStatus.COMPLETED.value
    await db.commit()
    
    # Requery with eager loading
    stmt = (
        select(Request)
        .where(Request.id == request_obj.id)
        .options(selectinload(Request.items), selectinload(Request.requested_by_user))
    )
    result = await db.execute(stmt)
    request_obj = result.scalar_one()
    
    # Batch fetch all parts for broadcast (avoid N+1)
    part_ids = [item.part_id for item in request_obj.items]
    if part_ids:
        parts_stmt = select(Part).where(Part.id.in_(part_ids))
        parts_result = await db.execute(parts_stmt)
        parts_map = {part.id: part for part in parts_result.scalars().all()}
        
        # Broadcast each item for real-time updates on supply page
        for item in request_obj.items:
            part = parts_map.get(item.part_id)
            if part:
                item_data: ItemDataDict = {
                    "id": str(item.id),
                    "part": {
                        "id": str(part.id),
                        "part_number": part.part_number,
                        "part_name": part.part_name,
                        "stock": part.stock,
                        "address": part.address,
                    },
                    "qty": item.qty,
                    "is_urgent": item.is_urgent,
                    "is_supplied": item.is_supplied,
                    "request": {
                        "id": str(request_obj.id),
                        "request_number": request_obj.request_number,
                        "destination": request_obj.destination,
                        "requested_at": request_obj.requested_at.isoformat(),
                    },
                }
                await broadcaster.broadcast_request_item_created(item_data)  # type: ignore
    
    return RequestResponse.model_validate(request_obj)


@router.put("/{request_id}/cancel", response_model=RequestResponse)
async def cancel_request(
    request_id: UUID,
    db: DB,
    current_user: CurrentUser,
) -> RequestResponse:
    """Cancel a request (transitions status → cancelled)."""
    # Permission: requests.cancel
    if not current_user.has_permission("requests.cancel"):
        raise HTTPException(status_code=403, detail="Permission denied: requests.cancel")
    
    stmt = (
        select(Request)
        .where(and_(Request.id == request_id, Request.deleted_at.is_(None)))
        .options(selectinload(Request.items), selectinload(Request.requested_by_user))
    )
    result = await db.execute(stmt)
    request_obj = result.scalar_one_or_none()

    if not request_obj:
        raise HTTPException(status_code=404, detail="Request not found")

    request_obj.status = DocumentStatus.CANCELLED.value
    await db.commit()
    
    stmt = (
        select(Request)
        .where(Request.id == request_obj.id)
        .options(selectinload(Request.items), selectinload(Request.requested_by_user))
    )
    result = await db.execute(stmt)
    return RequestResponse.model_validate(result.scalar_one())


@router.put("/items/{item_id}/supply", response_model=RequestResponse)
async def supply_request_item(
    item_id: UUID,
    db: DB,
    current_user: CurrentUser,
    qty: int | None = Query(default=None, ge=1, description="Quantity to supply"),
) -> RequestResponse:
    """Mark a request item as supplied and record outgoing movement."""
    # Permission: requests.supply
    if not current_user.has_permission("requests.supply"):
        raise HTTPException(status_code=403, detail="Permission denied: requests.supply")

    # Find the item
    stmt = select(RequestList).where(RequestList.id == item_id)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Request item not found")

    if item.is_supplied:
        raise HTTPException(status_code=409, detail="Item is already supplied")

    # Determine supply qty
    supply_qty = qty if qty is not None else item.qty

    # Lock part row for update
    part_stmt = select(Part).where(Part.id == item.part_id).with_for_update()
    part_result = await db.execute(part_stmt)
    part = part_result.scalar_one_or_none()

    if not part:
        raise HTTPException(status_code=404, detail="Part not found")
    if part.stock < supply_qty:
        raise HTTPException(status_code=400, detail=f"Not enough stock. Available: {part.stock}")

    # Process stock reduction
    stock_before = part.stock
    part.stock -= supply_qty
    stock_after = part.stock

    # Mark item as supplied
    item.is_supplied = True
    item.qty = supply_qty

    # --- Outgoing logic ---
    outgoing_stmt = select(Outgoing).where(
        and_(Outgoing.notes == str(item.request_id), Outgoing.status == "draft")
    )
    outgoing_result = await db.execute(outgoing_stmt)
    outgoing = outgoing_result.scalar_one_or_none()

    if not outgoing:
        today = datetime.now().strftime('%d%m%y')
        last_out_stmt = select(Outgoing).where(
            Outgoing.doc_number.like(f"OUT-{today}-%")
        ).order_by(Outgoing.doc_number.desc())
        last_out_result = await db.execute(last_out_stmt)
        last_out = last_out_result.scalars().first()
        
        last_seq = 0
        if last_out and last_out.doc_number:
            try:
                last_seq = int(last_out.doc_number.split('-')[-1])
            except (ValueError, IndexError):
                last_seq = 0
        
        new_seq = last_seq + 1
        doc_number = f"OUT-{today}-{new_seq:04d}"
        outgoing = Outgoing(
            id=uuid.uuid4(),
            doc_number=doc_number,
            issued_by=current_user.id,
            issued_at=datetime.now(),
            status="completed",
            notes=str(item.request_id)
        )
        db.add(outgoing)
        await db.flush()

    # Create OutgoingItem
    outgoing_item = OutgoingItem(
        id=uuid.uuid4(),
        outgoing_id=outgoing.id,
        part_id=part.id,
        qty=supply_qty
    )
    db.add(outgoing_item)

    # Create PartMovement
    movement = PartMovement(
        part_id=part.id,
        stock_before=stock_before,
        type="out",
        qty=supply_qty,
        stock_after=stock_after,
        reference_type="Outgoings",
        reference_id=outgoing.id
    )
    db.add(movement)

    await db.commit()

    # Broadcast event
    await broadcaster.broadcast_request_item_supplied(str(item_id), part.part_number)

    # Return the parent request
    request_stmt = (
        select(Request)
        .where(Request.id == item.request_id)
        .options(selectinload(Request.items), selectinload(Request.requested_by_user))
    )
    request_result = await db.execute(request_stmt)
    return RequestResponse.model_validate(request_result.scalar_one())