from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
app = FastAPI(title="Calendar API")

# Validations
# For calls except PATCH
class Event(BaseModel):
    id: str
    title: str
    starts_at: str   
    ends_at: str

# For PATCH call only
class EventUpdate(BaseModel):
    title: Optional[str] = None
    starts_at: Optional[str] = None
    ends_at: Optional[str] = None


# database reset at run time
DB_EVENTS: Dict[str, Event] = {}

# GET all events
@app.get("/events", response_model=List[Event])
def list_all_events():
    return list(DB_EVENTS.values())

# GET a specific event
@app.get("/events/{event_id}", response_model=Event)
def list_specific_event(event_id: str):
    if event_id not in DB_EVENTS:
        raise HTTPException(status_code=404, detail="Event not found")
    return DB_EVENTS[event_id]

# CREATE
@app.post("/events", response_model=Event, status_code=201)
def create_event(e: Event):
    if e.id in DB_EVENTS: # Check for duplicate id
        raise HTTPException(409, "Event id exists")
    DB_EVENTS[e.id] = e
    return e

# UPDATE
@app.patch("/events/{event_id}", response_model=Event)
def patch_event(event_id: str, partial: EventUpdate):
    if event_id not in DB_EVENTS:
        raise HTTPException(status_code=404, detail="Event not found")
    event = DB_EVENTS[event_id]
    updated_data = event.dict()

    for key, value in partial.dict(exclude_unset=True).items():
        updated_data[key] = value

    DB_EVENTS[event_id] = Event(**updated_data)
    return DB_EVENTS[event_id]

# REPLACE
@app.put("/events/{event_id}", response_model=Event)
def update_event(event_id: str, updated: Event):
    if event_id not in DB_EVENTS:
        raise HTTPException(status_code=404, detail="Event not found")
    if updated.id != event_id:
        raise HTTPException(status_code=400, detail="Body.id must match path event_id")
    DB_EVENTS[event_id] = updated
    return updated

# DELETE
@app.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: str):
    if event_id not in DB_EVENTS:
        raise HTTPException(status_code=404, detail="Event not found")
    del DB_EVENTS[event_id]
    return