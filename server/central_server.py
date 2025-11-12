import socket
import threading
import json
import time
from datetime import datetime
from queue import Queue, Empty
import sys
import os

# Add parent directory to path for pubsub import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pubsub import publish

class CentralServer:
    
    def __init__(self, host='localhost', tcp_port=8000, udp_port=8001):
        self.host = host
        self.tcp_port = tcp_port
        self.udp_socket = None
        self.udp_port = udp_port
        self.udp_clients = set()
        self.connected_clients = []
        self.lock = threading.Lock()
        self.calendar_events = []
        self.pomoTimer_state = {
            "running": False,
            "start_time": None,
            "duration": 25*60
        }
        self.shutdown_event = threading.Event()
        self.broadcast_q = Queue()
        self.clients_lock = threading.Lock()
    
    def start_server(self):
        print("Starting Central Productivity Server...")
        
        # TCP Server
        tcp_thread = threading.Thread(target=self._start_tcp_server, daemon=True, name="TCP-Server")
        tcp_thread.start()
        
        # UDP Server  
        udp_thread = threading.Thread(target=self._start_udp_server, daemon=True, name="UDP-Server")
        udp_thread.start()

        # Timer Manager
        timer_thread = threading.Thread(target=self._manage_timer, kwargs={"interval": 1.0}, daemon=True, name="Timer-Manager")
        timer_thread.start()
        
        # Message Sender
        sender_thread = threading.Thread(target=self._send_loop, daemon=True, name="Message-Sender")
        sender_thread.start()
        
        print(f"Central server running on {self.host}:{self.tcp_port}")
        print("   - TCP API: Calendar, Goals, Timer Control")
        print("   - UDP: Real-time broadcasts") 
        print("   - Hybrid: Works with P2P clients")
        
        try:
            while not self.shutdown_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nKeyboard interrupt detected. Stopping server...")
            self._stop_server()

    def _start_tcp_server(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_socket:
            tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            tcp_socket.bind((self.host, self.tcp_port))
            tcp_socket.listen(5)
            
            print(f"TCP server listening on {self.host}:{self.tcp_port}")
            
            while not self.shutdown_event.is_set():
                try:
                    client_socket, address = tcp_socket.accept()
                    print(f"TCP Connection from {address}")
                    
                    with self.clients_lock:
                        self.connected_clients.append(client_socket)
                    
                    client_thread = threading.Thread(
                        target=self._handle_tcp_client,
                        args=(client_socket, address),
                        daemon=True
                    )
                    client_thread.start()
                except OSError:
                    break

    def _start_udp_server(self):
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        try:
            self.udp_socket.bind((self.host, self.udp_port))
            print(f"UDP server listening on {self.host}:{self.udp_port}")
            
            while not self.shutdown_event.is_set():
                try:
                    data, address = self.udp_socket.recvfrom(1024)
                    message = json.loads(data.decode())
                    
                    with self.lock:
                        self.udp_clients.add(address)

                    self._broadcast_udp_message(message)
                except (OSError, json.JSONDecodeError):
                    pass
        finally:
            if self.udp_socket:
                self.udp_socket.close()

    def _handle_tcp_client(self, client_socket, address):
        buffer = b""
        try:
            while not self.shutdown_event.is_set():
                data = client_socket.recv(1024)
                if not data:
                    break
                
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line:
                        message = json.loads(line.decode("utf-8"))
                        self._process_tcp_message(message, client_socket)
                        
        except (ConnectionResetError, json.JSONDecodeError, OSError) as e:
            print(f"TCP Client {address} disconnected: {e}")
        finally:
            with self.clients_lock:
                if client_socket in self.connected_clients:
                    self.connected_clients.remove(client_socket)
            client_socket.close()

    def _process_tcp_message(self, message, client_socket):
        msg_type = message.get("type")
        
        if msg_type == "timer_control":
            self._handle_timer_control(message)
        elif msg_type == "calendar_event":
            self._handle_calendar_event(message)
        elif msg_type == "goal_update":
            self._handle_goal_update(message)
        elif msg_type == "request_sync":
            self._send_sync_data(client_socket)
        elif msg_type == "client_hello":
            self._handle_client_hello(message, client_socket)
        elif msg_type == "p2p_status":
            self._broadcast_tcp_message({
                "type": "p2p_acknowledge",
                "status": "connected"
            })

    def _handle_client_hello(self, message, client_socket):
        # Handle new client connection
        client_id = message.get("client_id", "unknown")
        p2p_capable = message.get("p2p_capable", False)
        
        print(f"👋 New client: {client_id} (P2P: {p2p_capable})")
        
        # Send current server state to new client
        self._send_sync_data(client_socket)

    def _handle_timer_control(self, message):
        action = message.get("action")
        
        if action == "start":
            with self.lock:
                self.pomoTimer_state["running"] = True
                self.pomoTimer_state["start_time"] = time.time()
            
        elif action == "stop":
            with self.lock:
                self.pomoTimer_state["running"] = False
            
        elif action == "set":
            with self.lock:
                self.pomoTimer_state = {
                    "running": False, 
                    "start_time": None, 
                    "duration": message.get("duration", 25*60)
                }
        
        # Broadcast timer state
        self._broadcast_tcp_message({
            "type": "timer_update",
            "timer_state": self.pomoTimer_state
        })
        
        # Publish to Redis
        publish("timer_controls", {
            "type": "timer_control",
            "action": action,
            "timer_state": self.pomoTimer_state,
            "timestamp": datetime.now().isoformat()
        })

    def _handle_calendar_event(self, message):
        incoming = message.get("event", {})
        
        with self.lock:
            event = dict(incoming)
            event["id"] = len(self.calendar_events) + 1
            event["created_at"] = datetime.now().isoformat()
            event["source"] = "central_server"
            self.calendar_events.append(event)
        
        # Broadcast to TCP clients
        self._broadcast_tcp_message({
            "type": "calendar_update",
            "event": event,
            "all_events": self.calendar_events
        })
        
        # Publish to Redis
        publish("calendar_events", {
            "type": "calendar_update",
            "event": event,
            "all_events": self.calendar_events,
            "source": "central",
            "timestamp": datetime.now().isoformat()
        })

    def _handle_goal_update(self, message):
        self._broadcast_tcp_message({
            "type": "goal_update",
            "goal": message.get("goal"),
            "user": message.get("user"),
            "completed": message.get("completed", False)
        })
        
        # Publish to Redis
        publish("goal_updates", {
            "type": "goal_update",
            "goal": message.get("goal"),
            "user": message.get("user"),
            "completed": message.get("completed", False),
            "timestamp": datetime.now().isoformat()
        })

    def _broadcast_tcp_message(self, message):
        self.broadcast_q.put(message)

    def _broadcast_udp_message(self, message):
        if not self.udp_socket:
            return
            
        message_json = json.dumps(message)
        
        with self.lock:
            for client_addr in self.udp_clients:
                try:
                    self.udp_socket.sendto(message_json.encode(), client_addr)
                except:
                    pass

    def _send_sync_data(self, client_socket):
        sync_data = {
            "type": "sync_data",
            "timer_state": self.pomoTimer_state,
            "calendar_events": self.calendar_events
        }
        try:
            client_socket.sendall((json.dumps(sync_data) + "\n").encode("utf-8"))
        except Exception:
            pass

    def _manage_timer(self, interval: float = 1.0):
        i = 0
        while not self.shutdown_event.is_set():
            # System heartbeat
            self.broadcast_q.put({"type": "heartbeat", "count": i, "time": time.time()})
            i += 1

            # Timer state updates
            with self.lock:
                running = self.pomoTimer_state["running"]
                start = self.pomoTimer_state["start_time"]
                dur = self.pomoTimer_state["duration"]

            if running and start is not None:
                elapsed = time.time() - start
                remaining = max(0, dur - elapsed)

                # Broadcast timer tick
                self.broadcast_q.put({
                    "type": "timer_tick",
                    "remaining_time": remaining,
                    "timer_state": self.pomoTimer_state
                })

                if remaining <= 0:
                    with self.lock:
                        self.pomoTimer_state["running"] = False
                    
                    self.broadcast_q.put({
                        "type": "timer_complete",
                        "timer_state": self.pomoTimer_state
                    })
                    
                    # Publish completion
                    publish("timer_controls", {
                        "type": "timer_complete",
                        "timer_state": self.pomoTimer_state,
                        "timestamp": datetime.now().isoformat()
                    })

            time.sleep(interval)

    def _send_loop(self):
        while not self.shutdown_event.is_set():
            try:
                message = self.broadcast_q.get(timeout=0.25)
            except Empty:
                continue
            
            try:
                wire = (json.dumps(message) + "\n").encode("utf-8")
                
                with self.clients_lock:
                    clients = list(self.connected_clients)
                
                for sock in clients:
                    try:
                        sock.sendall(wire)
                    except Exception:
                        with self.clients_lock:
                            if sock in self.connected_clients:
                                self.connected_clients.remove(sock)
            finally:
                self.broadcast_q.task_done()

    def _stop_server(self):
        self.shutdown_event.set()
        
        print("Shutting down central server...")
        
        # Close all client connections
        with self.clients_lock:
            for client in self.connected_clients:
                try:
                    client.close()
                except:
                    pass
            self.connected_clients.clear()

        # Close UDP socket
        if self.udp_socket:
            try:
                self.udp_socket.close()
            except:
                pass
        
        print("Central server shutdown complete")

    def get_server_info(self):
        # Get server status information
        with self.clients_lock:
            client_count = len(self.connected_clients)
        
        return {
            "type": "server_status",
            "clients_connected": client_count,
            "timer_running": self.pomoTimer_state["running"],
            "events_count": len(self.calendar_events),
            "hybrid_mode": True
        }

if __name__ == "__main__":
    server = CentralServer()
    server.start_server()