"""
Event broadcasting service for real-time updates using SSE.

This module provides an async event broadcaster that allows
multiple clients to subscribe to events and receive updates
in real-time using Server-Sent Events.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass
class Event:
    """Represents an event to be broadcast."""
    event_type: str
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=_utc_now)
    
    def to_sse(self) -> str:
        """Format event for SSE transmission."""
        payload: dict[str, Any] = {
            "type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }
        return f"data: {json.dumps(payload)}\n\n"


class EventBroadcaster:
    """
    Async event broadcaster for SSE.
    
    Manages multiple client subscriptions and broadcasts
    events to all connected clients.
    """
    
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._lock = asyncio.Lock()
    
    async def subscribe(self) -> AsyncGenerator[str, None]:
        """
        Subscribe to events.
        
        Yields SSE-formatted event strings as they arrive.
        """
        queue: asyncio.Queue[Event] = asyncio.Queue()
        
        async with self._lock:
            self._subscribers.add(queue)
            logger.info(f"New subscriber connected. Total: {len(self._subscribers)}")
        
        try:
            # Send initial connection event
            yield Event(
                event_type="connected",
                data={"message": "Connected to event stream"}
            ).to_sse()
            
            while True:
                try:
                    # Wait for events with a timeout to send keepalive
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield event.to_sse()
                except asyncio.TimeoutError:
                    # Send keepalive comment to prevent connection timeout
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            logger.info("Subscriber connection cancelled")
            raise
        finally:
            async with self._lock:
                self._subscribers.discard(queue)
                logger.info(f"Subscriber disconnected. Total: {len(self._subscribers)}")
    
    async def broadcast(self, event: Event) -> int:
        """
        Broadcast an event to all subscribers.
        
        Returns the number of subscribers that received the event.
        """
        async with self._lock:
            subscribers = list(self._subscribers)
        
        if not subscribers:
            return 0
        
        count = 0
        for queue in subscribers:
            try:
                queue.put_nowait(event)
                count += 1
            except asyncio.QueueFull:
                logger.warning("Subscriber queue full, event dropped")
        
        logger.info(f"Broadcast '{event.event_type}' to {count} subscribers")
        return count
    
    async def broadcast_request_item_created(self, item_data: dict[str, Any]) -> int:
        """Broadcast a new request item creation event."""
        event = Event(
            event_type="request_item_created",
            data=item_data,
        )
        return await self.broadcast(event)
    
    async def broadcast_request_item_supplied(self, item_id: str, part_number: str) -> int:
        """Broadcast when a request item is supplied."""
        event = Event(
            event_type="request_item_supplied",
            data={"item_id": item_id, "part_number": part_number},
        )
        return await self.broadcast(event)
    
    @property
    def subscriber_count(self) -> int:
        """Get the current number of subscribers."""
        return len(self._subscribers)


# Global broadcaster instance
broadcaster = EventBroadcaster()
