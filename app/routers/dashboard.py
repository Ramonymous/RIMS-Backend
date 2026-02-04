"""Dashboard router - aggregated statistics endpoint."""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.deps import CurrentUser
from app.models import Part, Receiving, Outgoing, Request, PartMovement
from app.schemas import (
    DashboardResponse,
    DashboardStats,
    PartsStats,
    ReceivingsStats,
    OutgoingsStats,
    RequestsStats,
    PartResponse,
    ReceivingResponse,
    OutgoingResponse,
    RequestResponse,
    PartMovementResponse,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Type alias for database dependency
DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    db: DB,
    current_user: CurrentUser,
    days: int = Query(default=30, ge=1, le=365, description="Number of days for recent movements"),
) -> DashboardResponse:
    """
    Get aggregated dashboard statistics.
    
    Returns counts and recent items for all major entities:
    - Parts: total, active, stock status breakdown
    - Receivings: total, by status, pending GR count
    - Outgoings: total, by status, pending GI count
    - Requests: total, by status
    - Recent movements (last N days)
    - Recent receivings, outgoings (last 5)
    - Low stock parts (up to 10)
    - Pending requests (up to 5)
    """
    # Calculate date range for movements
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # =========================================================================
    # PARTS STATISTICS (using SQL aggregation for accuracy)
    # =========================================================================
    parts_base = select(Part).where(Part.deleted_at.is_(None))
    
    # Total parts count
    total_parts = (await db.execute(
        select(func.count()).select_from(parts_base.subquery())
    )).scalar() or 0
    
    # Active parts count
    active_parts = (await db.execute(
        select(func.count()).select_from(
            parts_base.where(Part.is_active.is_(True)).subquery()
        )
    )).scalar() or 0
    
    # Stock status counts (using SQL CASE for efficiency)
    in_stock_count = (await db.execute(
        select(func.count()).select_from(
            parts_base.where(Part.stock > 10).subquery()
        )
    )).scalar() or 0
    
    low_stock_count = (await db.execute(
        select(func.count()).select_from(
            parts_base.where(and_(Part.stock > 0, Part.stock <= 10)).subquery()
        )
    )).scalar() or 0
    
    out_of_stock_count = (await db.execute(
        select(func.count()).select_from(
            parts_base.where(Part.stock <= 0).subquery()
        )
    )).scalar() or 0
    
    # =========================================================================
    # RECEIVINGS STATISTICS
    # =========================================================================
    receivings_base = select(Receiving).where(Receiving.deleted_at.is_(None))
    
    total_receivings = (await db.execute(
        select(func.count()).select_from(receivings_base.subquery())
    )).scalar() or 0
    
    draft_receivings = (await db.execute(
        select(func.count()).select_from(
            receivings_base.where(Receiving.status == "draft").subquery()
        )
    )).scalar() or 0
    
    completed_receivings = (await db.execute(
        select(func.count()).select_from(
            receivings_base.where(Receiving.status == "completed").subquery()
        )
    )).scalar() or 0
    
    pending_gr_count = (await db.execute(
        select(func.count()).select_from(
            receivings_base.where(
                and_(Receiving.status == "completed", Receiving.is_gr.is_(False))
            ).subquery()
        )
    )).scalar() or 0
    
    # =========================================================================
    # OUTGOINGS STATISTICS
    # =========================================================================
    outgoings_base = select(Outgoing).where(Outgoing.deleted_at.is_(None))
    
    total_outgoings = (await db.execute(
        select(func.count()).select_from(outgoings_base.subquery())
    )).scalar() or 0
    
    draft_outgoings = (await db.execute(
        select(func.count()).select_from(
            outgoings_base.where(Outgoing.status == "draft").subquery()
        )
    )).scalar() or 0
    
    completed_outgoings = (await db.execute(
        select(func.count()).select_from(
            outgoings_base.where(Outgoing.status == "completed").subquery()
        )
    )).scalar() or 0
    
    pending_gi_count = (await db.execute(
        select(func.count()).select_from(
            outgoings_base.where(
                and_(Outgoing.status == "completed", Outgoing.is_gi.is_(False))
            ).subquery()
        )
    )).scalar() or 0
    
    # =========================================================================
    # REQUESTS STATISTICS
    # =========================================================================
    requests_base = select(Request).where(Request.deleted_at.is_(None))
    
    total_requests = (await db.execute(
        select(func.count()).select_from(requests_base.subquery())
    )).scalar() or 0
    
    draft_requests = (await db.execute(
        select(func.count()).select_from(
            requests_base.where(Request.status == "draft").subquery()
        )
    )).scalar() or 0
    
    completed_requests = (await db.execute(
        select(func.count()).select_from(
            requests_base.where(Request.status == "completed").subquery()
        )
    )).scalar() or 0
    
    # =========================================================================
    # FETCH RECENT ITEMS
    # =========================================================================
    
    # Recent receivings (last 5)
    recent_receivings_result = await db.execute(
        select(Receiving)
        .where(Receiving.deleted_at.is_(None))
        .options(selectinload(Receiving.items))
        .order_by(Receiving.created_at.desc())
        .limit(5)
    )
    recent_receivings = recent_receivings_result.scalars().all()
    
    # Recent outgoings (last 5)
    recent_outgoings_result = await db.execute(
        select(Outgoing)
        .where(Outgoing.deleted_at.is_(None))
        .options(selectinload(Outgoing.items))
        .order_by(Outgoing.created_at.desc())
        .limit(5)
    )
    recent_outgoings = recent_outgoings_result.scalars().all()
    
    # Low stock parts (up to 10)
    low_stock_parts_result = await db.execute(
        select(Part)
        .where(and_(Part.deleted_at.is_(None), Part.stock > 0, Part.stock <= 10))
        .order_by(Part.stock.asc())
        .limit(10)
    )
    low_stock_parts = low_stock_parts_result.scalars().all()
    
    # Pending requests (draft status, up to 5)
    pending_requests_result = await db.execute(
        select(Request)
        .where(and_(Request.deleted_at.is_(None), Request.status == "draft"))
        .options(selectinload(Request.items), selectinload(Request.requested_by_user))
        .order_by(Request.created_at.desc())
        .limit(5)
    )
    pending_requests = pending_requests_result.scalars().all()
    
    # Recent movements (last N days, up to 100)
    recent_movements_result = await db.execute(
        select(PartMovement)
        .where(PartMovement.created_at >= start_date)
        .order_by(PartMovement.created_at.desc())
        .limit(100)
    )
    recent_movements = recent_movements_result.scalars().all()
    
    # =========================================================================
    # BUILD RESPONSE
    # =========================================================================
    stats = DashboardStats(
        parts=PartsStats(
            total=total_parts,
            active=active_parts,
            in_stock=in_stock_count,
            low_stock=low_stock_count,
            out_of_stock=out_of_stock_count,
        ),
        receivings=ReceivingsStats(
            total=total_receivings,
            draft=draft_receivings,
            completed=completed_receivings,
            pending_gr=pending_gr_count,
        ),
        outgoings=OutgoingsStats(
            total=total_outgoings,
            draft=draft_outgoings,
            completed=completed_outgoings,
            pending_gi=pending_gi_count,
        ),
        requests=RequestsStats(
            total=total_requests,
            draft=draft_requests,
            completed=completed_requests,
        ),
    )
    
    return DashboardResponse(
        stats=stats,
        recent_receivings=[ReceivingResponse.model_validate(r) for r in recent_receivings],
        recent_outgoings=[OutgoingResponse.model_validate(o) for o in recent_outgoings],
        low_stock_parts=[PartResponse.model_validate(p) for p in low_stock_parts],
        pending_requests=[RequestResponse.model_validate(r) for r in pending_requests],
        recent_movements=[PartMovementResponse.model_validate(m) for m in recent_movements],
    )
