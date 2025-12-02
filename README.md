# GroupSync - Virtual Group Productivity Platform

A distributed system for collaborative productivity with synchronized calendars, shared goals, and P2P Pomodoro timers. Built for CECS 327 at CSULB.

Team: Rebecca Mejia, Emmanuel Moye, Tin Nguyen, Bryan Tieu, Cole Triplett

Course: CECS 327 - Introduction to Networks and Distributed Computing

Instructor: Dr. Oscar Morales Ponce


## Quick Start

### Prerequisites
- Python 3.8+
- Redis server

### Installation & Running
```bash
# Install dependencies
pip install fastapi uvicorn redis pydantic

# Start Redis
redis-server

# Start the system
python main.py
# Server starts at http://localhost:8000

# Start a client (in separate terminal)
python client.py
```

### Verify Installation
```bash
curl http://localhost:8000/health
```

---

## Project Overview

Remote teams lack integrated productivity tools. Existing solutions operate separately, requiring manual coordination. GroupSync provides unified real-time collaboration.

### Architecture: Hybrid Model
- **Client-Server**: Calendar, goals, REST API (port 8000)
- **Peer-to-Peer**: Timer synchronization, real-time updates
- **Specialized Nodes**: Coordinator (8000), Goals (8100), Calendar (8200)

### Distributed System Characteristics
| Characteristic | Implementation |
|----------------|----------------|
| Heterogeneity | CLI clients, REST API, cross-platform |
| Concurrency | Threading with locks for shared resources |
| Scalability | Horizontal scaling with specialized nodes |
| Failure Handling | P2P leader election, 2PC transactions |
| Transparency | Users unaware of node distribution |
| Openness | REST API for external integration |

### Networking Protocols
- **TCP** (port 8000): Reliable transactions, 2PC coordination
- **UDP** (port 8001): Efficient timer tick broadcasts
- **HTTP/REST**: Web client API
- **Redis Pub/Sub**: Decoupled event broadcasting

---

## API Reference

### Calendar (/events)
```bash
# Create event
curl -X POST http://localhost:8000/events/ \
  -H "Content-Type: application/json" \
  -d '{"id":"meeting1","title":"Sync","starts_at":"2024-01-15T10:00:00","ends_at":"2024-01-15T11:00:00"}'

# List events
curl http://localhost:8000/events/
```

### Goals (/goals)
```bash
# Create goal
curl -X POST http://localhost:8000/goals/ \
  -H "Content-Type: application/json" \
  -d '{"id":"project1","title":"Complete System","owner":"team6"}'
```

### Pomodoro Timer (/pomo)
```bash
# Start timer
curl -X POST http://localhost:8000/pomo/start
```

---

## Demo Scenarios

### 1. Calendar Conflict Detection (2PC)
```bash
# Terminal 1: Book 2pm slot
curl -X POST http://localhost:8000/events/ \
  -d '{"id":"e1","title":"Meeting","starts_at":"2024-12-20T14:00:00"}'

# Terminal 2: Try same slot (will fail via 2PC)
curl -X POST http://localhost:8000/events/ \
  -d '{"id":"e2","title":"Conflict","starts_at":"2024-12-20T14:00:00"}'
# Returns: {"detail":"time_slot_taken"}
```

### 2. P2P Timer Failure Recovery
```bash
# Terminal 1: Start client as timer master
python client.py
> 1  # Start Timer

# Terminal 2: Join as peer
python client.py
> 3  # Join Timer
> localhost

# Kill Terminal 1
# Terminal 2 automatically promotes itself to master
```

### 3. Distributed Transactions
```bash
python client.py
> 4  # Begin Transaction (2PC)
> 1  # Add Calendar Event
> 3  # Commit Transaction
```

---

## Project Structure
- `main.py` - FastAPI server + socket server
- `client.py` - CLI client with P2P timer
- `api/` - REST API endpoints (calendar, goals, pomodoro)
- `server/` - Distributed server with 2PC and transactions
- `pubsub.py` - Redis Pub/Sub messaging

## Milestone Implementation Summary

### Milestone 1: Foundation
- **Hybrid Architecture**: Client-server for data consistency, P2P for real-time sync
- **Protocol Justification**: 
  - TCP for reliable transactions (calendar bookings via 2PC)
  - UDP for efficient timer broadcasts (tolerates packet loss)
  - HTTP/REST for web integration
  - Redis Pub/Sub for decoupled messaging

### Milestone 2: Communication Models
- **Direct IPC**: TCP/UDP sockets in `server/platform_server.py` for real-time sync
- **Remote Communication**: REST API in `api/` directory for web clients
- **Indirect Communication**: Redis Pub/Sub in `pubsub.py` for event broadcasting

### Milestone 3: Concurrency & P2P
- **Concurrency**: Threading with locks (`DB_LOCK`, `self.lock`) protects shared resources
- **P2P Design**: Hierarchical timer network with automatic leader election on failure
- **Validation**: System tested with multiple simultaneous users and simulated failures

### Milestone 4: Coordination & Consistency
- **Lamport Clocks**: Logical time in `client.py` ensures causal ordering
- **2PC Protocol**: Complete implementation in `server/platform_server.py` for atomic commits
- **Transaction Management**: Distributed locks prevent double-booking; timeout-based cleanup

## Validation
- Tested with 5+ concurrent clients
- Simulated network partitions and node failures
- Verified conflict detection in calendar bookings
- Confirmed P2P timer recovery on leader failure