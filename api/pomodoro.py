from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone
import time

from pubsub import publish

router = APIRouter(prefix="/pomo", tags=["Pomodoro"])

_socket_server_instance = None

def set_socket_server(server):
    global _socket_server_instance
    _socket_server_instance = server
    print(f"[Pomodoro] Socket server set: {server.server_id if server else None}")

def get_socket_server():
    return _socket_server_instance

@router.get("/state")
def get_pomo_state():
    server = get_socket_server()
    
    if server is None:
        raise HTTPException(503, "Timer server not available")
    
    try:
        # Get state with lock to ensure consistency
        with server.lock:
            state = server.pomoTimer_state.copy()
        
        start_time = state.get("start_time")
        
        # Convert start_time to ISO string if it exists
        if start_time:
            if isinstance(start_time, (int, float)):
                # Convert timestamp to datetime, then to ISO string
                dt = datetime.fromtimestamp(start_time, timezone.utc)
                state["start_time"] = dt.isoformat()
            elif hasattr(start_time, 'isoformat'):
                # Already a datetime object
                state["start_time"] = start_time.isoformat()
        
        # Calculate remaining time
        if state.get("running") and start_time:
            if isinstance(start_time, (int, float)):
                # Calculate elapsed time
                elapsed = time.time() - start_time
                remaining = state.get("duration", 1500) - elapsed
                state["remaining_time"] = max(0, remaining)
            else:
                # If start_time is not a number, use full duration
                state["remaining_time"] = state.get("duration", 1500)
        else:
            # Timer not running
            state["remaining_time"] = state.get("duration", 1500)
        
        return state
        
    except Exception as e:
        print(f"[Pomodoro API] Error getting timer state: {e}")
        import traceback
        traceback.print_exc()
        
        # Return safe default state
        return {
            "running": False,
            "start_time": None,
            "duration": 1500,
            "remaining_time": 1500
        }

@router.post("/start")
def start_pomo():
    server = get_socket_server()
    
    if server is None:
        raise HTTPException(503, "Timer server not available")
    
    server._handle_timer_control({"action": "start"})
    
    publish("timer_controls", {
        "type": "timer_control",
        "action": "start",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return {
        "status": "started",
        "type": "timer_control",
        "action": "start",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@router.post("/stop")
def stop_pomo():
    server = get_socket_server()
    
    if server is None:
        raise HTTPException(503, "Timer server not available")
    
    server._handle_timer_control({"action": "stop"})
    
    publish("timer_controls", {
        "type": "timer_control",
        "action": "stop",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return {
        "status": "stopped",
        "action": "stop",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@router.post("/set")
def set_pomo(duration_minutes: int = 25):
    server = get_socket_server()
    
    if server is None:
        raise HTTPException(503, "Timer server not available")
    
    server._handle_timer_control({
        "action": "set",
        "duration": duration_minutes * 60
    })
    
    publish("timer_controls", {
        "type": "timer_control",
        "action": "set",
        "duration": duration_minutes * 60,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return {
        "status": "set",
        "type": "timer_control",
        "action": "set",
        "duration": duration_minutes * 60,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }