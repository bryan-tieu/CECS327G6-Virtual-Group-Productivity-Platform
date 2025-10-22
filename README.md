# CECS327G6---Virtual-Group-Productivity-Platform
A real-time social productivity platform that allows remote users to synchronously follow a central pomodoro timer, share calendars, and track group goals. Built with a hybrid distributed architecture combining TCP/UDP sockets, REST APIs, and Redis Pub/Sub messaging.


# Component Details

### PlatformServer (`server.py`)
**Purpose**: Core real-time communication server handling TCP/UDP connections and state management.

**Features**:
- TCP/UDP socket server (TCP:9000, UDP:9001)
- Real-time client synchronization
- Thread-safe state management
- Automatic client connection handling
- Manages: Timer state, Calendar events, Goal updates

**Run Independently**:
```bash
python server.py
```


### FastAPI Server (`main.py`)
**Purpose**: REST API interface for web clients and external integrations.

**Features**:
- FastAPI documentation at `/docs`
- Automatic real-time broadcasting on API calls
- Go to: http://localhost:8000/docs

**Run Independently**:
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```


### Redis Pub/Sub (`pubsub.py`)
**Purpose**: Asynchronous message broadcasting with space and time uncoupling.

**Features**:
- Channel-based messaging
- Background thread message processing
- Decoupled component communication

**Channels**:
- `timer_updates` - Timer state changes and ticks
- `calendar_events` - Event creation and modifications
- `goal_updates` - Goal changes and completions

## API Modules

### Pomodoro Timer (`api/pomodoro.py`)
**Purpose**: Synchronized team Pomodoro timer management.

**Endpoints**:
- GET    /pomo/state - Get current timer state
- POST   /pomo/start - Start the timer
- POST   /pomo/set - Set timer duration (minutes)



### Calendar Management (`api/calendar.py`)
**Purpose**: Shared team calendar with real-time event synchronization.

**Endpoints**:
- GET    /events/ - List all events
- GET    /events/{event_id} - Get specific event
- POST   /events/ - Create new event
- PUT    /events/{event_id} - Replace event
- PATCH  /events/{event_id} - Partial update
- DELETE /events/{event_id} - Delete event

### Goal Board (`api/goalboard.py`)
**Purpose**: Collaborative team goal tracking and progress monitoring.

**Endpoints**:

- GET    /goals/ - List all goals
- GET    /goals/{goal_id} - Get specific goal
- POST   /goals/ - Create new goal
- PATCH  /goals/{goal_id} - Update goal
- DELETE /goals/{goal_id} - Delete goal

## Requirements & Dependencies

### Core Dependencies

# Runtime Dependencies
- fastapi>=0.104.0
- uvicorn>=0.24.0
- redis>=5.0.0
- pydantic>=2.0.0


### System Requirements
- **Python**: 3.8+
- **Redis Server**: 5.0+
- **Network**: Ports 8000 (HTTP), 9000 (TCP), 9001 (UDP) available


### 1. Install Dependencies
```bash
pip install fastapi uvicorn redis pydantic
```

### 2. Start Redis Server
```bash
# On Ubuntu
sudo systemctl start redis-server
```

### 3. Run the Complete System

```bash
# Start the FastAPI server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Verify System Status
```bash
# Check if servers are running
curl http://localhost:8000/docs
```