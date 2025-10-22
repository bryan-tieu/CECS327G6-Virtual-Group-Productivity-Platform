# main.py
from fastapi import FastAPI
import threading

from server import PlatformServer
from api import calendar, pomodoro, goalboard

# Create singleton PlatformServer
socket_server = PlatformServer()

# Start socket server in background
threading.Thread(target=socket_server.start_server, daemon=True).start()

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