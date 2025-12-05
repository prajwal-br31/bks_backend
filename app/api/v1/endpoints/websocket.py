from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.notifications.websocket_manager import websocket_manager

router = APIRouter()


@router.websocket("/notifications")
async def websocket_notifications(websocket: WebSocket, user_id: str = "anonymous"):
    """
    WebSocket endpoint for real-time notifications.
    
    Connect with: ws://host/api/v1/ws/notifications?user_id=<user_id>
    
    Messages sent to client:
    {
        "type": "notification",
        "notification_type": "email",
        "title": "...",
        "message": "...",
        "data": {...}
    }
    """
    await websocket_manager.connect(websocket, user_id)
    
    try:
        while True:
            # Keep connection alive and handle incoming messages
            data = await websocket.receive_text()
            
            # Handle ping/pong for keepalive
            if data == "ping":
                await websocket.send_text("pong")
            
            # Could handle other message types here
            
    except WebSocketDisconnect:
        await websocket_manager.disconnect(websocket)
    except Exception:
        await websocket_manager.disconnect(websocket)


@router.get("/stats", response_model=dict)
async def websocket_stats():
    """Get WebSocket connection statistics."""
    return {
        "active_connections": websocket_manager.connection_count,
        "unique_users": websocket_manager.user_count,
    }

