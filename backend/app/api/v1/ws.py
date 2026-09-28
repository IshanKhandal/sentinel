"""Realtime WebSocket endpoint and observability routes.

Protocol Standards:
- docs/realtime-contract.md
- Stage 14 Directive Sections 5, 6, 14, 15, 21, 22
- WebSocket Gateway Endpoint: ws://<host>:<port>/api/v1/ws/events
- Fallback Alias: ws://<host>:<port>/api/v1/ws
"""

import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from backend.app.services.realtime.manager import websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])


@router.websocket("/ws/events")
@router.websocket("/ws")
async def websocket_events_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(default=None, description="Optional authentication token or ticket")
) -> None:
    """Realtime WebSocket telemetry, alert push, and system status feed.
    
    docs/realtime-contract.md:
    Endpoint: ws://<host>:<port>/api/v1/ws/events
    Lifecycle:
    1. Client connects with optional token query parameter.
    2. Server verifies token (rejects with 4401 if invalid).
    3. Server sends connection.acknowledged packet.
    4. Client exchanges ping/pong heartbeat and topic subscription updates.
    5. Disconnect triggers automatic resource cleanup.
    
    Security Boundary: AUTHORIZATION HARDENING DEFERRED TO STAGE 15.
    """
    connection = await websocket_manager.connect(websocket=websocket, token=token)
    if connection is None:
        return

    try:
        while True:
            raw_text = await websocket.receive_text()
            await websocket_manager.handle_client_message(connection.session_id, raw_text)
    except WebSocketDisconnect:
        await websocket_manager.disconnect(connection.session_id, code=1000, reason="Client disconnected normally")
    except Exception as exc:
        logger.warning(f"WebSocket session {connection.session_id} terminated unexpectedly: {exc}")
        await websocket_manager.disconnect(connection.session_id, code=1011, reason="Unexpected server exception")


@router.get("/ws/metrics", tags=["realtime"])
def get_websocket_metrics() -> Dict[str, Any]:
    """Retrieve operational metrics for active WebSocket connections and throughput.
    
    docs/realtime-contract.md & Stage 14 Directive Section 22.
    """
    return {
        "status": "ONLINE",
        "metrics": websocket_manager.get_metrics(),
    }
