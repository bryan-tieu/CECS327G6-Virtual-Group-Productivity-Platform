# api/pomodoro.py
from fastapi import APIRouter
from datetime import datetime, timezone

from server import PlatformServer
from pubsub import publish

# Use the existing socket server instance
router = APIRouter(prefix="/pomo", tags=["Pomodoro"])
socket_server: PlatformServer = None

@router.get("/state")
def get_pomo_state():
    state = socket_server.pomoTimer_state.copy()

    start_time = state.get("start_time")

    # Convert datetime object to ISO string for JSON
    if start_time:
        state["start_time"] = start_time.isoformat()

    # If the timer is running, calculate elapsed and remaining time
    if state["running"] and start_time:
        elapsed = (datetime.now(timezone.utc) - socket_server.pomoTimer_state["start_time"]).total_seconds()
        remaining = state["duration"] - elapsed
        state["remaining_time"] = max(0, remaining)
    else:
        state["remaining_time"] = state["duration"]

    return state


@router.post("/start")
def start_pomo():
    socket_server._handle_timer_control({"action": "start"})
    publish("timer_controls",{
        "type": "timer_control",
        "action": "start",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    return {"status": "started",
            "type": "timer_control",
            "action": "start",
            "timestamp": datetime.now(timezone.utc).isoformat()}

@router.post("/set")
def set_pomo(duration_minutes: int=25):
    socket_server._handle_timer_control({
        "action": "set",
        "duration": duration_minutes * 60
    })
    publish("timer_controls", {
        "type": "timer_control",
        "action": "set",
        "duration": duration_minutes * 60,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    return {"status": "set",
            "type": "timer_control",
            "action": "set",
            "duration": duration_minutes * 60,
            "timestamp": datetime.now(timezone.utc).isoformat()
            }