"""
Main entry point for GroupSync.

This file orchestrates:
- FastAPI REST API server
- Distributed PlatformServer nodes
- Redis Pub/Sub integration
- 2PC coordination simulation

Architecture: Hybrid client-server + P2P with distributed transactions
Protocols: TCP, UDP, HTTP, Redis Pub/Sub
"""

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

# Configure logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global state for distributed nodes
servers = {}
coordinator = None
calendar_node = None
goals_node = None
subscriber_manager = None
demo_coordinator = None

def initialize_system():
    """
    Initialize the entire distributed system:
    1. Launches distributed server nodes (coordinator, goals, calendar)
    2. Injects socket server dependencies into API routers
    3. Initializes Redis Pub/Sub system
    4. Sets up 2PC coordination simulation
    """
    global servers, coordinator, calendar_node, goals_node, subscriber_manager, demo_coordinator
    
    logger.info("Initializing Group Productivity Platform...")
    
    # Step 1: Launch distributed servers using specialized nodes
    servers = launch_distributed_servers()
    coordinator = servers.get('S1')  # Coordinator node
    goals_node = servers.get('S2')   # Goals specialization node
    calendar_node = servers.get('S3')  # Calendar specialization node
    
    # Step 2: Dependency injection for API routers
    # Connects the REST API layer with the socket communication layer
    if coordinator:
        calendar.set_socket_server(coordinator)
        pomodoro.set_socket_server(coordinator)
        goalboard.set_socket_server(coordinator)
        
        logger.info(f"Socket server injected into API routers")
    else:
        logger.error("NO COORDINATOR AVAILABLE! Falling back to single server mode.")
        
    # Step 3: Initialize Pub/Sub system for indirect communication
    try:
        subscriber_manager = start_global_subscriber()
        logger.info("Pub/Sub system ready for decoupled messaging")
    except Exception as e:
        logger.warning(f"Pub/Sub initialization failed: {e}")
    
    # Step 4: Initialize 2PC coordination demo
    participants = [
        Participant("Bryan"),
        Participant("Cole"),
        Participant("Tin"),
        Participant("Rebecca"),
        Participant("Emmanuel")
    ]
    demo_coordinator = Coordinator(participants)
    logger.info("2PC coordination system initialized")

# Create FastAPI app with metadata
app = FastAPI(
    title="GroupSync API",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# Include REST API routers
app.include_router(calendar.router)
app.include_router(pomodoro.router)
app.include_router(goalboard.router)

@app.get("/")
def read_root():
    """
    Root endpoint provides system overview.
    
    Returns basic information about the distributed system architecture and available endpoints.
    """
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
    """
    Health check endpoint for monitoring distributed system status.
    
    Checks availability of all components:
    - Coordinator node
    - Specialized nodes (calendar, goals)
    - Pub/Sub system
    - Socket server injection status
    
    Used for system monitoring and debugging. So much debugging.
    """
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
    """
    Debug endpoint to verify dependency injection status.
    
    Troubleshoot connection between:
    - REST API layer (FastAPI)
    - Socket communication layer (PlatformServer)
    - Distributed transaction coordination
    
    Returns info about socket server injection.
    """
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
    """
    FastAPI startup event handler.
    
    Initializes the distributed system when the FastAPI server starts.
    Ensures all components are ready before handling requests.
    """
    logger.info("FastAPI starting up - initializing system...")
    initialize_system()

if __name__ == "__main__":
    # Start the combined FastAPI + socket server system
    uvicorn.run(
        "main:app",
        host="0.0.0.0",  # Bind to all interfaces
        port=8000,        # HTTP port for REST API
        reload=True,      # Development mode auto-reload
        log_level="info"
    )