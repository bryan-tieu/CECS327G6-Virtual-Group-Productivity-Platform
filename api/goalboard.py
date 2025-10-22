# api/goalboard.py
import threading
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from typing import Dict, List, Optional
from datetime import datetime

from server import PlatformServer
from pubsub import publish

router = APIRouter(prefix="/goals", tags=["Group Goals"])
socket_server: PlatformServer = None

# --- Models ---
class Goal(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    owner: str
    completed: bool = False
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()

class GoalUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    completed: Optional[bool] = None


# --- In-memory storage ---
DB_GOALS: Dict[str, Goal] = {}
DB_LOCK = threading.Lock()


# --- Routes ---
@router.get("/", response_model=List[Goal])
def list_goals():
    return list(DB_GOALS.values())


@router.get("/{goal_id}", response_model=Goal)
def get_goal(goal_id: str):
    if goal_id not in DB_GOALS:
        raise HTTPException(404, "Goal not found")
    return DB_GOALS[goal_id]


@router.post("/", response_model=Goal, status_code=201)
def create_goal(goal: Goal):
    with DB_LOCK:
        if goal.id in DB_GOALS:
            raise HTTPException(409, "Goal ID already exists")
        DB_GOALS[goal.id] = goal

    socket_server._broadcast_tcp_message({
        "type": "goal_update",
        "action": "create",
        "goal": goal.model_dump(),
        "all_goals": [g.model_dump() for g in DB_GOALS.values()],
        "timestamp": datetime.now().isoformat()
    })
    publish("goal_updates", {
        "type": "goal_update",
        "action": "create",
        "goal": goal.model_dump(),
        "all_goals": [g.model_dump() for g in DB_GOALS.values()],
        "timestamp": datetime.now().isoformat(),
    })

    return goal


@router.patch("/{goal_id}", response_model=Goal)
def update_goal(goal_id: str, update: GoalUpdate):
    """Edit or mark a goal as completed."""
    with DB_LOCK:
        if goal_id not in DB_GOALS:
            raise HTTPException(404, "Goal not found")
        goal = DB_GOALS[goal_id].model_dump()
        goal.update(update.model_dump(exclude_unset=True))
        goal["updated_at"] = datetime.now()
        DB_GOALS[goal_id] = Goal(**goal)

    socket_server._broadcast_tcp_message({
        "type": "goal_update",
        "action": "update",
        "goal": DB_GOALS[goal_id].model_dump(),
        "all_goals": [g.model_dump() for g in DB_GOALS.values()],
        "timestamp": datetime.now().isoformat(),
    })

    publish("goal_updates", {
        "type": "goal_update",
        "action": "update",
        "goal": DB_GOALS[goal_id].model_dump(),
        "all_goals": [g.model_dump() for g in DB_GOALS.values()],
        "timestamp": datetime.now().isoformat(),
    })
    return DB_GOALS[goal_id]


@router.delete("/{goal_id}", status_code=204)
def delete_goal(goal_id: str):
    with DB_LOCK:
        if goal_id not in DB_GOALS:
            raise HTTPException(404, "Goal not found")
        deleted = DB_GOALS[goal_id]
        del DB_GOALS[goal_id]


    socket_server._broadcast_tcp_message({
        "type": "goal_delete",
        "action": "delete",
        "goal": deleted.model_dump(),
        "all_goals": [g.model_dump() for g in DB_GOALS.values()],
        "timestamp": datetime.now().isoformat(),
    })
    publish("goal_updates", {
        "type": "goal_delete",
        "action": "delete",
        "goal": deleted.model_dump(),
        "all_goals": [g.model_dump() for g in DB_GOALS.values()],
        "timestamp": datetime.now().isoformat(),
    })
    return Response(status_code=204)
