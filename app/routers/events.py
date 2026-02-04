"""Server-Sent Events (SSE) router for real-time updates."""

import logging
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.events import broadcaster

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/stream")
async def event_stream():
    """
    SSE endpoint for real-time event streaming.
    
    Clients connect to this endpoint to receive real-time updates
    for new request items, supply confirmations, etc.
    
    Usage:
        const eventSource = new EventSource('/events/stream');
        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            console.log(data);
        };
    """
    return StreamingResponse(
        broadcaster.subscribe(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/status")
async def event_status() -> dict[str, int | str]:
    """Get the current status of the event broadcaster."""
    return {
        "subscriber_count": broadcaster.subscriber_count,
        "status": "active",
    }
