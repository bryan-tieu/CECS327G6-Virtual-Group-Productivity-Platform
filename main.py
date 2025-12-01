# main.py
import threading
import time
import logging

from fastapi import FastAPI
import uvicorn

from server.server_launcher import launch_distributed_servers
from api import calendar, pomodoro, goalboard
from pubsub import publish
from subscribe import start_global_subscriber
from coordination import Coordinator, Participant

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global state
servers = {}
coordinator = None
calendar_node = None
goals_node = None
subscriber_manager = None
demo_coordinator = None

def initialize_system():
    global servers, coordinator, calendar_node, goals_node, subscriber_manager, demo_coordinator
    
    logger.info("Initializing Group Productivity Platform...")
    
    # Launch distributed servers
    servers = launch_distributed_servers()
    coordinator = servers.get('S1')
    goals_node = servers.get('S2')
    calendar_node = servers.get('S3')
    
    # Inject dependencies into API routers
    if coordinator:
        from api import calendar, pomodoro, goalboard
        calendar.set_socket_server(coordinator)
        pomodoro.set_socket_server(coordinator)
        goalboard.set_socket_server(coordinator)
        
        logger.info(f"Calendar socket_server after injection: {calendar.get_socket_server()}")
        logger.info(f"Calendar socket_server type: {type(calendar.get_socket_server())}")
        logger.info(f"Has _broadcast_tcp_message: {hasattr(calendar.get_socket_server(), '_broadcast_tcp_message')}")
    else:
        logger.error("NO COORDINATOR AVAILABLE!")
        
    # Initialize pub/sub
    try:
        subscriber_manager = start_global_subscriber()
        logger.info("Pub/Sub system ready")
    except Exception as e:
        logger.warning(f"Pub/Sub initialization failed: {e}")
    
    # Initialize 2PC demo
    participants = [
        Participant("Bryan"),
        Participant("Cole"),
        Participant("Tin"),
        Participant("Rebecca"),
        Participant("Emmanuel")
    ]
    demo_coordinator = Coordinator(participants)


# Create FastAPI app FIRST
app = FastAPI(
    title="Group Productivity Platform API",
    description="Distributed system with 2PC transactions and hybrid architecture",
    version="3.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# Include routers
app.include_router(calendar.router)
app.include_router(pomodoro.router)
app.include_router(goalboard.router)

@app.get("/")
def read_root():
    # Check if socket_server is actually set
    socket_status = "available" if calendar.get_socket_server() else "unavailable"
    return {
        "message": "Group Productivity Platform",
        "version": "3.0.0",
        "architecture": "Distributed 2PC with Hybrid P2P",
        "socket_server_status": socket_status,
        "endpoints": {
            "calendar": "/events",
            "goals": "/goals", 
            "pomodoro": "/pomo",
            "health": "/health",
            "debug": "/debug/injection"
        }
    }

@app.get("/health")
def health_check():
    socket_available = calendar.get_socket_server() is not None
    socket_has_method = hasattr(calendar.get_socket_server(), '_broadcast_tcp_message') if socket_available else False
    
    return {
        "status": "healthy" if socket_available else "degraded",
        "timestamp": time.time(),
        "services": {
            "coordinator": coordinator is not None,
            "calendar_node": calendar_node is not None,
            "goals_node": goals_node is not None,
            "pubsub": subscriber_manager is not None,
            "socket_server_injected": socket_available,
            "socket_server_has_method": socket_has_method
        }
    }

@app.get("/debug/injection")
def debug_injection():
    from api import calendar, pomodoro, goalboard
    
    return {
        "calendar_socket_server": str(calendar.get_socket_server()) if calendar.get_socket_server() else "None",
        "calendar_socket_server_type": str(type(calendar.get_socket_server())) if calendar.get_socket_server() else "None",
        "pomodoro_socket_server": str(pomodoro.get_socket_server()) if pomodoro.get_socket_server() else "None",
        "goalboard_socket_server": str(goalboard.get_socket_server()) if goalboard.get_socket_server() else "None",
        "main_coordinator": str(coordinator) if coordinator else "None",
        "same_object": calendar.get_socket_server() is coordinator if calendar.get_socket_server() and coordinator else False,
        "has_broadcast_method": hasattr(calendar.get_socket_server(), '_broadcast_tcp_message') if calendar.get_socket_server() else False
    }

@app.on_event("startup")
async def startup_event():
    logger.info("FastAPI starting up - initializing system...")
    initialize_system()

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )