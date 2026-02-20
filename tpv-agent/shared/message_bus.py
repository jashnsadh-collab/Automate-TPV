"""
shared/message_bus.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
In-memory message bus with stream semantics.
Drop-in replacement for Redis Streams in production.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Stream names
STREAM_TPV = "tpv.forecasts"
STREAM_ALERTS = "tpv.alerts"
STREAM_STATUS = "tpv.status"


class MessageBus:
    """
    Async in-memory message bus.
    In production: replace with Redis Streams / Kafka / NATS JetStream.
    """

    def __init__(self):
        self._streams: Dict[str, List[Tuple[str, Dict]]] = defaultdict(list)
        self._subscribers: Dict[str, List[asyncio.Queue]] = defaultdict(list)
        self._history: List[Dict[str, Any]] = []

    async def publish(
        self,
        stream: str,
        payload: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> str:
        msg_id = str(uuid.uuid4())[:8]
        trace_id = trace_id or str(uuid.uuid4())

        envelope = {
            "msg_id": msg_id,
            "trace_id": trace_id,
            "stream": stream,
            "timestamp": datetime.utcnow().isoformat(),
            "payload": payload,
        }

        self._streams[stream].append((msg_id, payload))
        self._history.append(envelope)

        # Notify subscribers
        for queue in self._subscribers[stream]:
            await queue.put((msg_id, payload))

        logger.debug("Published to %s: msg_id=%s trace=%s", stream, msg_id, trace_id)
        return msg_id

    async def publish_alert(
        self,
        alert_type: str,
        payload: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> str:
        payload["alert_type"] = alert_type
        return await self.publish(STREAM_ALERTS, payload, trace_id)

    async def subscribe(
        self,
        stream: str,
        group: str = "default",
        consumer: str = "consumer-1",
    ) -> AsyncIterator[Tuple[str, Dict]]:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[stream].append(queue)
        logger.info("Subscribed to %s  group=%s  consumer=%s", stream, group, consumer)
        try:
            while True:
                msg_id, payload = await queue.get()
                yield msg_id, payload
        finally:
            self._subscribers[stream].remove(queue)

    async def ack(self, stream: str, group: str, msg_id: str) -> None:
        """Acknowledge message processing (no-op for in-memory bus)."""
        pass

    def get_history(self, stream: Optional[str] = None, limit: int = 100) -> List[Dict]:
        if stream:
            return [m for m in self._history if m["stream"] == stream][-limit:]
        return self._history[-limit:]

    def get_latest(self, stream: str) -> Optional[Dict]:
        msgs = self._streams.get(stream, [])
        if msgs:
            return msgs[-1][1]
        return None
