"""
Goal Board API module with real-time updates.

Implements REST API endpoints for collaborative goal tracking with:
- Real-time synchronization via Redis Pub/Sub
- Thread-safe concurrent access
- Integration with distributed architecture

Provides shared goal management for team productivity.
"""

import threading
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from typing import Dict, List, Optional
from datetime import datetime

from pubsub import publish

router = APIRouter(prefix="/goals", tags=["Group Goals"])

# Socket server instance for real-time broadcasting
_socket_server_instance = None

def set_socket_server(server):
    """
    Set socket server instance for goal update broadcasting.
    
    Args:
        server: PlatformServer instance
    """
    global _socket_server_instance
    _socket_server_instance = server
    print(f"[Goalboard] Socket server set: {server.server_id if server else None}")

def get_socket_server():
    """Get current socket server instance."""
    return _socket_server_instance

# Data Models

class Goal(BaseModel):
    """
    Goal data model for team productivity tracking.
    
    Attributes:
        id: Unique goal identifier
        title: Goal title
        description: Optional detailed description
        owner: User who owns the goal
        completed: Completion status (default: False)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """
    id: str
    title: str
    description: Optional[str] = None
    owner: str
    completed: bool = False
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()

class GoalUpdate(BaseModel):
    """
    Partial goal update model for PATCH operations.
    
    Supports updating individual goal fields without replacing entire goal.
    """
    title: Optional[str] = None
    description: Optional[str] = None
    completed: Optional[bool] = None

# In-Memory Storage

DB_GOALS: Dict[str, Goal] = {}
DB_LOCK = threading.Lock()  # Thread lock for concurrent access

# API Endpoints

@router.get("/", response_model=List[Goal])
def list_goals():
    """
    List all team goals.
    
    Returns:
        List[Goal]: All goals in the system
    """
    return list(DB_GOALS.values())

@router.get("/{goal_id}", response_model=Goal)
def get_goal(goal_id: str):
    """
    Get specific goal by ID.
    
    Args:
        goal_id: Goal identifier
        
    Returns:
        Goal: Requested goal
        
    Raises:
        HTTPException: 404 if goal not found
    """
    if goal_id not in DB_GOALS:
        raise HTTPException(404, "Goal not found")
    return DB_GOALS[goal_id]

@router.post("/", response_model=Goal, status_code=201)
def create_goal(goal: Goal):
    """
    Create new team goal.
    
    Features:
    - Thread-safe goal creation
    - Real-time broadcast to all clients
    - Redis Pub/Sub notification
    - Automatic timestamp generation
    
    Args:
        goal: Goal to create
        
    Returns:
        Goal: Created goal
        
    Raises:
        HTTPException: 409 if goal ID already exists
    """
    server = get_socket_server()
    
    with DB_LOCK:
        if goal.id in DB_GOALS:
            raise HTTPException(409, "Goal ID already exists")
        DB_GOALS[goal.id] = goal

    # Broadcast via socket server if available
    if server:
        try:
            server._broadcast_tcp_message({
                "type": "goal_update",
                "action": "create",
                "goal": goal.model_dump(),
                "all_goals": [g.model_dump() for g in DB_GOALS.values()],
                "timestamp": datetime.now().isoformat()
            })
        except Exception as e:
            print(f"[Goalboard] Broadcast failed: {e}")

    # Publish to Redis Pub/Sub for decoupled communication
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
    """
    Update existing goal.
    
    Supports partial updates and automatically updates timestamp.
    Broadcasts changes to all connected clients.
    
    Args:
        goal_id: Goal identifier
        update: Partial update data
        
    Returns:
        Goal: Updated goal
        
    Raises:
        HTTPException: 404 if goal not found
    """
    server = get_socket_server()
    
    with DB_LOCK:
        if goal_id not in DB_GOALS:
            raise HTTPException(404, "Goal not found")
        # Merge existing goal with updates
        goal = DB_GOALS[goal_id].model_dump()
        goal.update(update.model_dump(exclude_unset=True))
        goal["updated_at"] = datetime.now()  # Update timestamp
        DB_GOALS[goal_id] = Goal(**goal)

    # Broadcast update
    if server:
        try:
            server._broadcast_tcp_message({
                "type": "goal_update",
                "action": "update",
                "goal": DB_GOALS[goal_id].model_dump(),
                "all_goals": [g.model_dump() for g in DB_GOALS.values()],
                "timestamp": datetime.now().isoformat(),
            })
        except Exception as e:
            print(f"[Goalboard] Broadcast failed: {e}")

    # Publish to Redis
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
    """
    Delete team goal.
    
    Removes goal and broadcasts deletion to all clients.
    
    Args:
        goal_id: Goal identifier to delete
        
    Returns:
        Response: 204 No Content on success
        
    Raises:
        HTTPException: 404 if goal not found
    """
    server = get_socket_server()
    
    with DB_LOCK:
        if goal_id not in DB_GOALS:
            raise HTTPException(404, "Goal not found")
        deleted = DB_GOALS[goal_id]
        del DB_GOALS[goal_id]

    # Broadcast deletion
    if server:
        try:
            server._broadcast_tcp_message({
                "type": "goal_delete",
                "action": "delete",
                "goal": deleted.model_dump(),
                "all_goals": [g.model_dump() for g in DB_GOALS.values()],
                "timestamp": datetime.now().isoformat(),
            })
        except Exception as e:
            print(f"[Goalboard] Broadcast failed: {e}")

    # Publish deletion event
    publish("goal_updates", {
        "type": "goal_delete",
        "action": "delete",
        "goal": deleted.model_dump(),
        "all_goals": [g.model_dump() for g in DB_GOALS.values()],
        "timestamp": datetime.now().isoformat(),
    })
    return Response(status_code=204)