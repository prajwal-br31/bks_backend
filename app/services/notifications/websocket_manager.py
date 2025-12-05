import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    Manages WebSocket connections for real-time notifications.
    
    Supports:
    - Multiple connections per user
    - Broadcast to all users
    - Targeted messages to specific users
    """

    def __init__(self):
        # Map of user_id -> list of WebSocket connections
        self._connections: Dict[str, List[WebSocket]] = {}
        # Map of WebSocket -> user_id (for cleanup)
        self._websocket_to_user: Dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: str = "anonymous"):
        """
        Accept a new WebSocket connection.
        
        Args:
            websocket: The WebSocket connection
            user_id: User identifier (for targeted messages)
        """
        await websocket.accept()
        
        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = []
            self._connections[user_id].append(websocket)
            self._websocket_to_user[websocket] = user_id
        
        logger.info(f"WebSocket connected: user={user_id}")

    async def disconnect(self, websocket: WebSocket):
        """
        Remove a WebSocket connection.
        
        Args:
            websocket: The WebSocket to remove
        """
        async with self._lock:
            user_id = self._websocket_to_user.pop(websocket, None)
            if user_id and user_id in self._connections:
                try:
                    self._connections[user_id].remove(websocket)
                    if not self._connections[user_id]:
                        del self._connections[user_id]
                except ValueError:
                    pass
        
        logger.info(f"WebSocket disconnected: user={user_id}")

    async def send_to_user(self, user_id: str, message: dict):
        """
        Send a message to all connections for a specific user.
        
        Args:
            user_id: Target user ID
            message: Message to send (will be JSON encoded)
        """
        async with self._lock:
            connections = self._connections.get(user_id, []).copy()
        
        disconnected = []
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to user {user_id}: {e}")
                disconnected.append(websocket)
        
        # Clean up disconnected sockets
        for ws in disconnected:
            await self.disconnect(ws)

    async def broadcast(self, message: dict, exclude_user: Optional[str] = None):
        """
        Broadcast a message to all connected clients.
        
        Args:
            message: Message to send (will be JSON encoded)
            exclude_user: Optional user to exclude from broadcast
        """
        async with self._lock:
            all_connections = [
                (user_id, ws)
                for user_id, connections in self._connections.items()
                for ws in connections
                if user_id != exclude_user
            ]
        
        disconnected = []
        for user_id, websocket in all_connections:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to broadcast to user {user_id}: {e}")
                disconnected.append(websocket)
        
        # Clean up
        for ws in disconnected:
            await self.disconnect(ws)

    async def send_notification(
        self,
        notification_type: str,
        title: str,
        message: str,
        data: Optional[dict] = None,
        user_id: Optional[str] = None,
    ):
        """
        Send a notification to users.
        
        Args:
            notification_type: Type of notification (e.g., "email", "document")
            title: Notification title
            message: Notification message
            data: Additional data to include
            user_id: If provided, send only to this user; otherwise broadcast
        """
        payload = {
            "type": "notification",
            "notification_type": notification_type,
            "title": title,
            "message": message,
            "data": data or {},
            "timestamp": asyncio.get_event_loop().time(),
        }
        
        if user_id:
            await self.send_to_user(user_id, payload)
        else:
            await self.broadcast(payload)

    @property
    def connection_count(self) -> int:
        """Get total number of active connections."""
        return sum(len(connections) for connections in self._connections.values())

    @property
    def user_count(self) -> int:
        """Get number of unique connected users."""
        return len(self._connections)


# Global instance
websocket_manager = WebSocketManager()

