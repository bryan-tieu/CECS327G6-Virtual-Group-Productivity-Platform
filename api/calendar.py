# api/calendar.py
import threading

from fastapi import FastAPI, HTTPException, Response, APIRouter
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime

from server import PlatformServer
from pubsub import publish

router = APIRouter(prefix="/events", tags=["Calendar"])
socket_server: PlatformServer = None

# Validations
# For calls except PATCH
class Event(BaseModel):
    id: str
    title: str
    starts_at: datetime
    ends_at: datetime

# For PATCH call only
class EventUpdate(BaseModel):
    title: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None


# database reset at run time
DB_EVENTS: Dict[str, Event] = {}
DB_LOCK = threading.Lock()

# GET all events
@router.get("/", response_model=List[Event])
def list_all_events():
    return list(DB_EVENTS.values())

# GET a specific event
@router.get("/{event_id}", response_model=Event)
def list_specific_event(event_id: str):
    if event_id not in DB_EVENTS:
        raise HTTPException(status_code=404, detail="Event not found")
    return DB_EVENTS[event_id]

# CREATE
@router.post("/", response_model=Event, status_code=201)
def create_event(e: Event):
    with DB_LOCK:
        if e.id in DB_EVENTS: # Check for duplicate id
            raise HTTPException(409, "Event id exists")
        DB_EVENTS[e.id] = e

    socket_server._broadcast_tcp_message({
        "type": "calendar_update",
        "event": e.model_dump(),
        "all_events": [ev.model_dump() for ev in DB_EVENTS.values()],
        "action": "create",
        "timestamp": datetime.now().isoformat()
    })

    publish("calendar_events",{
        "type": "calendar_update",
        "event": e.model_dump(),
        "all_events": [ev.model_dump() for ev in DB_EVENTS.values()],
        "action": "create",
        "timestamp": datetime.now().isoformat()
    })

    return e

# UPDATE
@router.patch("/{event_id}", response_model=Event)
def patch_event(event_id: str, partial: EventUpdate):
    with DB_LOCK:
        if event_id not in DB_EVENTS:
            raise HTTPException(status_code=404, detail="Event not found")
        event = DB_EVENTS[event_id].model_dump()
        event.update(partial.model_dump(exclude_unset=True))
        DB_EVENTS[event_id] = Event(**event)

    socket_server._broadcast_tcp_message({
        "type": "calendar_update",
        "event": DB_EVENTS[event_id].model_dump(),
        "all_events": [ev.model_dump() for ev in DB_EVENTS.values()],
        "action": "update",
        "timestamp": datetime.now().isoformat()
    })

    publish("calendar_events", {
        "type": "calendar_update",
        "event": DB_EVENTS[event_id].model_dump(),
        "all_events": [ev.model_dump() for ev in DB_EVENTS.values()],
        "action": "update",
        "timestamp": datetime.now().isoformat()
    })

    return DB_EVENTS[event_id]

# REPLACE
@router.put("/{event_id}", response_model=Event)
def update_event(event_id: str, updated: Event):
    with DB_LOCK:
        if event_id not in DB_EVENTS:
            raise HTTPException(status_code=404, detail="Event not found")
        if updated.id != event_id:
            raise HTTPException(status_code=400, detail="Body.id must match path event_id")
        DB_EVENTS[event_id] = updated

    socket_server._broadcast_tcp_message({
        "type": "calendar_update",
        "event": updated.model_dump(),
        "all_events": [ev.model_dump() for ev in DB_EVENTS.values()],
        "action": "replace",
        "timestamp": datetime.now().isoformat()
    })

    publish("calendar_events", {
        "type": "calendar_update",
        "event": updated.model_dump(),
        "all_events": [ev.model_dump() for ev in DB_EVENTS.values()],
        "action": "replace",
        "timestamp": datetime.now().isoformat()
    })

    return updated

# DELETE
@router.delete("/{event_id}", status_code=204)
def delete_event(event_id: str):
    with DB_LOCK:
        if event_id not in DB_EVENTS:
            raise HTTPException(status_code=404, detail="Event not found")
        deleted = DB_EVENTS[event_id]
        del DB_EVENTS[event_id]

    socket_server._broadcast_tcp_message({
        "type": "calendar_delete",
        "event": deleted.model_dump(),
        "all_events": [ev.model_dump() for ev in DB_EVENTS.values()],
        "action": "delete",
        "timestamp": datetime.now().isoformat()
    })

    publish("calendar_events", {
        "type": "calendar_delete",
        "event": deleted.model_dump(),
        "all_events": [ev.model_dump() for ev in DB_EVENTS.values()],
        "action": "delete",
        "timestamp": datetime.now().isoformat()
    })

    return Response(status_code=204)