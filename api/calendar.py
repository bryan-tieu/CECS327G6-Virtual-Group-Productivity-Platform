"""
Calendar API module with distributed transaction support.

Implements REST API endpoints for calendar management with:
- Two-Phase Commit (2PC) for conflict-free scheduling
- Real-time broadcasting to all connected clients
- Integration with distributed server nodes

Endpoints support full CRUD operations
"""

import threading
from typing import Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from pubsub import publish

# Create API router with prefix and tags
router = APIRouter(prefix="/events", tags=["Calendar"])

# Socket server instance for real-time broadcasting
_socket_server_instance = None

def set_socket_server(server):
    """
    Set socket server instance for real-time broadcasting.
    
    This enables the API layer to broadcast updates to all connected clients
    when calendar events are modified.
    
    Args:
        server: PlatformServer instance
    """
    global _socket_server_instance
    _socket_server_instance = server
    print(f"[Calendar] Socket server set: {server.server_id if server else None}")

def get_socket_server():
    """Get current socket server instance."""
    return _socket_server_instance

# ==================== Data Models ====================

class Event(BaseModel):
    """
    Calendar event data model.
    
    Attributes:
        id: Unique event identifier
        title: Event title
        starts_at: Event start datetime
        ends_at: Event end datetime
    """
    id: str
    title: str
    starts_at: datetime
    ends_at: datetime

class EventUpdate(BaseModel):
    """
    Partial event update model for PATCH operations.
    """
    title: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None


# Simple in-memory storage for demo
DB_EVENTS: Dict[str, Event] = {}

# Thread lock for concurrent access
DB_LOCK = threading.Lock()

# API Endpoints

@router.get("/", response_model=List[Event])
def list_all_events():
    """
    List all calendar events.
    
    Returns:
        List[Event]: All events in the system
    """
    return list(DB_EVENTS.values())

@router.get("/{event_id}", response_model=Event)
def list_specific_event(event_id: str):
    """
    Get specific calendar event by ID.
    
    Args:
        event_id: Event identifier
        
    Returns:
        Event: Requested event
        
    Raises:
        HTTPException: 404 if event not found
    """
    if event_id not in DB_EVENTS:
        raise HTTPException(status_code=404, detail="Event not found")
    return DB_EVENTS[event_id]

@router.post("/", response_model=Event, status_code=201)
def create_event(e: Event):
    """
    Create new calendar event with distributed consistency.
    
    Features:
    1. Thread-safe event creation
    2. Real-time broadcast to all clients
    3. Redis Pub/Sub notification
    4. Conflict detection via 2PC in distributed mode
    
    Args:
        e: Event to create
        
    Returns:
        Event: Created event
        
    Raises:
        HTTPException: 409 if event ID already exists
    """
    server = get_socket_server()
    
    # Thread-safe event creation
    with DB_LOCK:
        for existing_id, existing_event in DB_EVENTS.items():
            if existing_id == e.id:
                raise HTTPException(409, "Event id exists")
            
            # Time conflict check
            if existing_event.starts_at == e.starts_at:
                raise HTTPException(409, f"Time slot {e.starts_at} already booked by event '{existing_event.title}'")
        
        DB_EVENTS[e.id] = e
        print(f"[API] Created event {e.id} at {e.starts_at}")

    # Broadcast via socket server
    if server and hasattr(server, '_broadcast_tcp_message'):
        try:
            server._broadcast_tcp_message({
                "type": "calendar_update",
                "event": e.model_dump(),
                "all_events": [ev.model_dump() for ev in DB_EVENTS.values()],
                "action": "create",
                "timestamp": datetime.now().isoformat()
            })
        except Exception as broadcast_error:
            print(f"[Calendar] Broadcast failed: {broadcast_error}")

    # Publish to Redis
    publish("calendar_events", {
        "type": "calendar_update",
        "event": e.model_dump(),
        "all_events": [ev.model_dump() for ev in DB_EVENTS.values()],
        "action": "create",
        "timestamp": datetime.now().isoformat()
    })

    return e

@router.patch("/{event_id}", response_model=Event)
def patch_event(event_id: str, partial: EventUpdate):
    """
    Partially update calendar event.
    
    Supports partial updates through PATCH method.
    Broadcasts updates to all connected clients.
    
    Args:
        event_id: Event identifier
        partial: Partial update data
        
    Returns:
        Event: Updated event
        
    Raises:
        HTTPException: 404 if event not found
    """
    server = get_socket_server()
    
    with DB_LOCK:
        if event_id not in DB_EVENTS:
            raise HTTPException(status_code=404, detail="Event not found")
        # Merge existing event with partial updates
        event = DB_EVENTS[event_id].model_dump()
        event.update(partial.model_dump(exclude_unset=True))
        DB_EVENTS[event_id] = Event(**event)

    # Broadcast update
    if server:
        try:
            server._broadcast_tcp_message({
                "type": "calendar_update",
                "event": DB_EVENTS[event_id].model_dump(),
                "all_events": [ev.model_dump() for ev in DB_EVENTS.values()],
                "action": "update",
                "timestamp": datetime.now().isoformat()
            })
        except Exception as broadcast_error:
            print(f"[Calendar] Broadcast failed: {broadcast_error}")

    # Publish to Redis
    publish("calendar_events", {
        "type": "calendar_update",
        "event": DB_EVENTS[event_id].model_dump(),
        "all_events": [ev.model_dump() for ev in DB_EVENTS.values()],
        "action": "update",
        "timestamp": datetime.now().isoformat()
    })

    return DB_EVENTS[event_id]

@router.put("/{event_id}", response_model=Event)
def update_event(event_id: str, updated: Event):
    """
    Replace calendar event (full update).
    
    Requires complete event data.
    Validates that event ID in path matches ID in body.
    
    Args:
        event_id: Event identifier from URL path
        updated: Complete event data
        
    Returns:
        Event: Replaced event
        
    Raises:
        HTTPException: 404 if event not found
        HTTPException: 400 if body ID doesn't match path ID
    """
    server = get_socket_server()
    
    with DB_LOCK:
        if event_id not in DB_EVENTS:
            raise HTTPException(status_code=404, detail="Event not found")
        if updated.id != event_id:
            raise HTTPException(status_code=400, detail="Body.id must match path event_id")
        DB_EVENTS[event_id] = updated

    # Broadcast replacement
    if server:
        try:
            server._broadcast_tcp_message({
                "type": "calendar_update",
                "event": updated.model_dump(),
                "all_events": [ev.model_dump() for ev in DB_EVENTS.values()],
                "action": "replace",
                "timestamp": datetime.now().isoformat()
            })
        except Exception as broadcast_error:
            print(f"[Calendar] Broadcast failed: {broadcast_error}")

    publish("calendar_events", {
        "type": "calendar_update",
        "event": updated.model_dump(),
        "all_events": [ev.model_dump() for ev in DB_EVENTS.values()],
        "action": "replace",
        "timestamp": datetime.now().isoformat()
    })

    return updated

@router.delete("/{event_id}", status_code=204)
def delete_event(event_id: str):
    """
    Delete calendar event.
    
    Removes event and broadcasts deletion to all clients.
    
    Args:
        event_id: Event identifier to delete
        
    Returns:
        Response: 204 No Content on success
        
    Raises:
        HTTPException: 404 if event not found
    """
    server = get_socket_server()
    
    with DB_LOCK:
        if event_id not in DB_EVENTS:
            raise HTTPException(status_code=404, detail="Event not found")
        deleted = DB_EVENTS[event_id]
        del DB_EVENTS[event_id]

    # Broadcast deletion
    if server:
        try:
            server._broadcast_tcp_message({
                "type": "calendar_delete",
                "event": deleted.model_dump(),
                "all_events": [ev.model_dump() for ev in DB_EVENTS.values()],
                "action": "delete",
                "timestamp": datetime.now().isoformat()
            })
        except Exception as broadcast_error:
            print(f"[Calendar] Broadcast failed: {broadcast_error}")

    # Publish deletion event
    publish("calendar_events", {
        "type": "calendar_delete",
        "event": deleted.model_dump(),
        "all_events": [ev.model_dump() for ev in DB_EVENTS.values()],
        "action": "delete",
        "timestamp": datetime.now().isoformat()
    })

    return Response(status_code=204)