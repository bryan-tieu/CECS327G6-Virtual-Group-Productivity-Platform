# main.py
from fastapi import FastAPI
import threading
import logging

from server.server import PlatformServer
from api import calendar, pomodoro, goalboard
from subscribe import start_global_subscriber

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create singleton PlatformServer
socket_server = PlatformServer()

# Start socket server in background
threading.Thread(target=socket_server.start_server, daemon=True).start()

# Start Redis pub/sub for indirect communication
logger.info("Starting Redis Pub/Sub subscribers...")
subscriber = start_global_subscriber()
logger.info("Indirect communication system ready")

# Inject server instance into routers
calendar.socket_server = socket_server
pomodoro.socket_server = socket_server
goalboard.socket_server = socket_server

# Create FastAPI app
app = FastAPI(title="Platform API")

# Include routers
app.include_router(calendar.router)
app.include_router(pomodoro.router)
app.include_router(goalboard.router)

@app.get("/")
def read_root():
    return {"message": "Group Productivity Platform API"}

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "services": {
            "fastapi": "running",
            "socket_server": "running", 
            "redis_pubsub": "running"
        }
    }

@app.get("/pubsub/stats")
def get_pubsub_stats():
    """Get pub/sub statistics"""
    return subscriber.get_stats()