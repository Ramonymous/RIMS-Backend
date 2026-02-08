"""Dashboard router - aggregated statistics endpoint."""

from datetime import datetime, timedelta
from typing import Annotated

import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, case, func, select
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

_DASHBOARD_CACHE_TTL_SECONDS = 10.0
_dashboard_cache: dict[int, tuple[float, DashboardResponse]] = {}

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
    cached = _dashboard_cache.get(days)
    now = time.monotonic()
    if cached is not None:
        cached_at, cached_value = cached
        if now - cached_at <= _DASHBOARD_CACHE_TTL_SECONDS:
            return cached_value

    # Calculate date range for movements
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # =========================================================================
    # PARTS STATISTICS (using SQL aggregation for accuracy)
    # =========================================================================
    parts_stats_row = (
        await db.execute(
            select(
                func.count(Part.id),
                func.coalesce(func.sum(case((Part.is_active.is_(True), 1), else_=0)), 0),
                func.coalesce(func.sum(case((Part.stock > 10, 1), else_=0)), 0),
                func.coalesce(
                    func.sum(case((and_(Part.stock > 0, Part.stock <= 10), 1), else_=0)), 0
                ),
                func.coalesce(func.sum(case((Part.stock <= 0, 1), else_=0)), 0),
            ).where(Part.deleted_at.is_(None))
        )
    ).one()
    total_parts, active_parts, in_stock_count, low_stock_count, out_of_stock_count = (
        int(parts_stats_row[0] or 0),
        int(parts_stats_row[1] or 0),
        int(parts_stats_row[2] or 0),
        int(parts_stats_row[3] or 0),
        int(parts_stats_row[4] or 0),
    )
    
    # =========================================================================
    # RECEIVINGS STATISTICS
    # =========================================================================
    receivings_stats_row = (
        await db.execute(
            select(
                func.count(Receiving.id),
                func.coalesce(func.sum(case((Receiving.status == "draft", 1), else_=0)), 0),
                func.coalesce(func.sum(case((Receiving.status == "completed", 1), else_=0)), 0),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(Receiving.status == "completed", Receiving.is_gr.is_(False)),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            ).where(Receiving.deleted_at.is_(None))
        )
    ).one()
    total_receivings, draft_receivings, completed_receivings, pending_gr_count = (
        int(receivings_stats_row[0] or 0),
        int(receivings_stats_row[1] or 0),
        int(receivings_stats_row[2] or 0),
        int(receivings_stats_row[3] or 0),
    )
    
    # =========================================================================
    # OUTGOINGS STATISTICS
    # =========================================================================
    outgoings_stats_row = (
        await db.execute(
            select(
                func.count(Outgoing.id),
                func.coalesce(func.sum(case((Outgoing.status == "draft", 1), else_=0)), 0),
                func.coalesce(func.sum(case((Outgoing.status == "completed", 1), else_=0)), 0),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(Outgoing.status == "completed", Outgoing.is_gi.is_(False)),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            ).where(Outgoing.deleted_at.is_(None))
        )
    ).one()
    total_outgoings, draft_outgoings, completed_outgoings, pending_gi_count = (
        int(outgoings_stats_row[0] or 0),
        int(outgoings_stats_row[1] or 0),
        int(outgoings_stats_row[2] or 0),
        int(outgoings_stats_row[3] or 0),
    )
    
    # =========================================================================
    # REQUESTS STATISTICS
    # =========================================================================
    requests_stats_row = (
        await db.execute(
            select(
                func.count(Request.id),
                func.coalesce(func.sum(case((Request.status == "draft", 1), else_=0)), 0),
                func.coalesce(func.sum(case((Request.status == "completed", 1), else_=0)), 0),
            ).where(Request.deleted_at.is_(None))
        )
    ).one()
    total_requests, draft_requests, completed_requests = (
        int(requests_stats_row[0] or 0),
        int(requests_stats_row[1] or 0),
        int(requests_stats_row[2] or 0),
    )
    
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
    
    response = DashboardResponse(
        stats=stats,
        recent_receivings=[ReceivingResponse.model_validate(r) for r in recent_receivings],
        recent_outgoings=[OutgoingResponse.model_validate(o) for o in recent_outgoings],
        low_stock_parts=[PartResponse.model_validate(p) for p in low_stock_parts],
        pending_requests=[RequestResponse.model_validate(r) for r in pending_requests],
        recent_movements=[PartMovementResponse.model_validate(m) for m in recent_movements],
    )

    _dashboard_cache[days] = (now, response)
    return response
