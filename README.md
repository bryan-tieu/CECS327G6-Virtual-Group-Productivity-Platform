
# CECS327G6---Virtual-Group-Productivity-Platform

A real-time social productivity platform that allows remote users to synchronously follow a central pomodoro timer, share calendars, and track group goals. Built with a hybrid distributed architecture combining TCP/UDP sockets, REST APIs, and Redis Pub/Sub messaging.

## Quick Start

### System Requirements
- **Python**: 3.8+
- **Redis Server**: 5.0+
- **Network**: Ports 8000 (HTTP), 9000 (TCP), 9001 (UDP) available

### 1. Install Dependencies
```bash
pip install fastapi uvicorn redis pydantic requests
```

### 2. Start Redis Server
```bash
# On Ubuntu/Debian
sudo systemctl start redis-server

# Or run directly
redis-server
```

### 3. Run the Complete System
```bash
# Start the FastAPI server (includes socket server and pub/sub)
python main.py

# Or use uvicorn directly
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Verify System Status
```bash
# Check if servers are running
curl http://localhost:8000/health
```

## Test Cases & Verification

### API Endpoint Tests

#### 1. Pomodoro Timer Tests
```bash
# Get current timer state
curl http://localhost:8000/pomo/state

# Start the timer
curl -X POST http://localhost:8000/pomo/start

# Set timer to 15 minutes
curl -X POST "http://localhost:8000/pomo/set?duration_minutes=15"
```

#### 2. Calendar Management Tests
```bash
# Create a new event
curl -X POST http://localhost:8000/events/ \
  -H "Content-Type: application/json" \
  -d '{
    "id": "event1",
    "title": "Team Meeting",
    "starts_at": "2024-01-15T10:00:00",
    "ends_at": "2024-01-15T11:00:00"
  }'

# List all events
curl http://localhost:8000/events/

# Get specific event
curl http://localhost:8000/events/event1

# Update event
curl -X PATCH http://localhost:8000/events/event1 \
  -H "Content-Type: application/json" \
  -d '{"title": "Updated Team Meeting"}'

# Delete event
curl -X DELETE http://localhost:8000/events/event1
```

#### 3. Goal Board Tests
```bash
# Create a new goal
curl -X POST http://localhost:8000/goals/ \
  -H "Content-Type: application/json" \
  -d '{
    "id": "goal1",
    "title": "Complete Project Milestone",
    "description": "Finish the distributed system implementation",
    "owner": "alice"
  }'

# List all goals
curl http://localhost:8000/goals/

# Mark goal as completed
curl -X PATCH http://localhost:8000/goals/goal1 \
  -H "Content-Type: application/json" \
  -d '{"completed": true}'

# Delete goal
curl -X DELETE http://localhost:8000/goals/goal1
```

### System Integration Tests

#### 4. Real-time Communication Test
```bash
# Test 1: Start timer and verify real-time updates
# In one terminal, start the server, then in another:
curl -X POST http://localhost:8000/pomo/start

# You should see timer updates in the server logs
```

#### 5. Pub/Sub System Test
```bash
# Check pub/sub statistics
curl http://localhost:8000/pubsub/stats

# Trigger demo events
curl http://localhost:8000/pubsub/demo
```

#### 6. Hybrid System Test
```bash
# Test the complete hybrid system
python -c "
from hybrid import HybridPlatform
platform = HybridPlatform()
platform.start_hybrid_system(start_clients=2)
print('Hybrid system started with 2 P2P clients')
import time
time.sleep(10)
platform.stop()
"
```

## Architecture & Components

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
- Redis Pub/Sub integration
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
- `platform_events` - General system events

## API Modules

### Pomodoro Timer (`api/pomodoro.py`)
**Purpose**: Synchronized team Pomodoro timer management.

**Endpoints**:
- `GET    /pomo/state` - Get current timer state
- `POST   /pomo/start` - Start the timer
- `POST   /pomo/set` - Set timer duration (minutes)

### Calendar Management (`api/calendar.py`)
**Purpose**: Shared team calendar with real-time event synchronization.

**Endpoints**:
- `GET    /events/` - List all events
- `GET    /events/{event_id}` - Get specific event
- `POST   /events/` - Create new event
- `PUT    /events/{event_id}` - Replace event
- `PATCH  /events/{event_id}` - Partial update
- `DELETE /events/{event_id}` - Delete event

### Goal Board (`api/goalboard.py`)
**Purpose**: Collaborative team goal tracking and progress monitoring.

**Endpoints**:
- `GET    /goals/` - List all goals
- `GET    /goals/{goal_id}` - Get specific goal
- `POST   /goals/` - Create new goal
- `PATCH  /goals/{goal_id}` - Update goal
- `DELETE /goals/{goal_id}` - Delete goal

## Testing

### Performance
```bash
# Test concurrent connections
for i in {1..10}; do
  curl -X POST http://localhost:8000/events/ \
    -H "Content-Type: application/json" \
    -d "{\"id\": \"perf$i\", \"title\": \"Test Event $i\", \"starts_at\": \"2024-01-15T10:00:00\", \"ends_at\": \"2024-01-15T11:00:00\"}" &
done
wait
```

### Fault Tolerance
```bash
# Test system recovery
# 1. Start the system
# 2. Kill Redis server temporarily
# 3. Restart Redis
# 4. Verify system recovers and continues functioning
```

## Troubleshooting

1. **Redis Connection Failed**
   ```bash
   # Check if Redis is running
   redis-cli ping
   # Start Redis if not running
   redis-server
   ```

2. **Port Already in Use**
   ```bash
   # Find process using port
   lsof -i :8000
   # Kill the process or use different port
   ```

## Dependencies

### Core Dependencies
```txt
fastapi>=0.104.0
uvicorn>=0.24.0
redis>=5.0.0
pydantic>=2.0.0
requests>=2.31.0
```
