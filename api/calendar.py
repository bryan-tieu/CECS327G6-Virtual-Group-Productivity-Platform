# api/calendar.py
import threading
from typing import Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from pubsub import publish

router = APIRouter(prefix="/events", tags=["Calendar"])

# ========== SINGLETON PATTERN ==========
_socket_server_instance = None

def set_socket_server(server):
    """Set the socket server instance - called by main.py"""
    global _socket_server_instance
    _socket_server_instance = server
    print(f"[Calendar] Socket server set: {server.server_id if server else None}")

def get_socket_server():
    """Get socket server instance"""
    return _socket_server_instance
# ========== END SINGLETON ==========

# Models
class Event(BaseModel):
    id: str
    title: str
    starts_at: datetime
    ends_at: datetime

class EventUpdate(BaseModel):
    title: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None

# Database
DB_EVENTS: Dict[str, Event] = {}
DB_LOCK = threading.Lock()

# Routes
@router.get("/", response_model=List[Event])
def list_all_events():
    return list(DB_EVENTS.values())

@router.get("/{event_id}", response_model=Event)
def list_specific_event(event_id: str):
    if event_id not in DB_EVENTS:
        raise HTTPException(status_code=404, detail="Event not found")
    return DB_EVENTS[event_id]

@router.post("/", response_model=Event, status_code=201)
def create_event(e: Event):
    # Get server (from singleton)
    server = get_socket_server()
    
    with DB_LOCK:
        if e.id in DB_EVENTS:
            raise HTTPException(409, "Event id exists")
        DB_EVENTS[e.id] = e

    # Broadcast if server available
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
            # Continue anyway - publish to Redis still works

    # Always publish to Redis
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
    # Get server (with lazy loading)
    server = get_socket_server()
    
    with DB_LOCK:
        if event_id not in DB_EVENTS:
            raise HTTPException(status_code=404, detail="Event not found")
        event = DB_EVENTS[event_id].model_dump()
        event.update(partial.model_dump(exclude_unset=True))
        DB_EVENTS[event_id] = Event(**event)

    # Broadcast if server available
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
    # Get server (with lazy loading)
    server = get_socket_server()
    
    with DB_LOCK:
        if event_id not in DB_EVENTS:
            raise HTTPException(status_code=404, detail="Event not found")
        if updated.id != event_id:
            raise HTTPException(status_code=400, detail="Body.id must match path event_id")
        DB_EVENTS[event_id] = updated

    # Broadcast if server available
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
    # Get server (with lazy loading)
    server = get_socket_server()
    
    with DB_LOCK:
        if event_id not in DB_EVENTS:
            raise HTTPException(status_code=404, detail="Event not found")
        deleted = DB_EVENTS[event_id]
        del DB_EVENTS[event_id]

    # Broadcast if server available
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

    publish("calendar_events", {
        "type": "calendar_delete",
        "event": deleted.model_dump(),
        "all_events": [ev.model_dump() for ev in DB_EVENTS.values()],
        "action": "delete",
        "timestamp": datetime.now().isoformat()
    })

    return Response(status_code=204)