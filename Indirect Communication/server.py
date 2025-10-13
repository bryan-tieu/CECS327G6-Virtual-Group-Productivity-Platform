import socket
import threading
import json
import time
from datetime import datetime

class PlatformServer:
    
    # Init
    def __init__(self, host='localhost', tcp_port=8000, udp_port = 8001):
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
            "duration" : 25*60
        }
    
    # Starting the central server
    def start_server(self):
        
        print("Starting platform server...")
        
        # TCP
        tcp_thread = threading.Thread(target=self._start_tcp_server)
        tcp_thread.daemon = True
        tcp_thread.start()
        
        # UDP
        udp_thread = threading.Thread(target=self._start_udp_server)
        udp_thread.daemon = True
        udp_thread.start()

        # Timer
        timer_thread = threading.Thread(target=self._manage_timer)
        timer_thread.daemon = True
        timer_thread.start()
        
        try:
            
            while True:
                
                time.sleep(1)
        
        except KeyboardInterrupt:
            print("\nKeyboard input detected.\nStopping server...")
            self._stop_server    
    
    # TCP helper
    def _start_tcp_server(self):
        
        # TCP Socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_socket:
            
            tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            tcp_socket.bind((self.host, self.tcp_port))
            tcp_socket.listen(5)
            
            print(f"TCP server listening on {self.host}:{self.tcp_port}")
            
            while True:
                
                client_socket, address = tcp_socket.accept()
                
                print(f"TCP Connection established with address: {address}")
                
                with self.lock:
                    self.connected_clients.append(client_socket)
                
                client_thread = threading.Thread(
                    target=self._handle_tcp_client,
                    args=(client_socket, address)
                )
                
                client_thread.daemon = True
                client_thread.start()
    
    # UDP Helper
    def _start_udp_server(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            
            udp_socket.bind((self.host, self.udp_port))
            
            print(f"UDP server listening on {self.host}:{self.udp_port}")
            
            while True:
                try:                
                    data, address = udp_socket.recvfrom(1024)
                    message = json.loads(data.decode())
                    
                    with self.lock:
                        self.udp_clients.add(address)

                    self._broadcast_udp_message(message, udp_socket)

                except OSError:
                    break

    # Client operations for TCP
    def _handle_tcp_client(self, client_socket, address):
        
        try:
            
            while True:
                
                data = client_socket.recv(1024)
                
                if not data:
                    break
                
                message = json.loads(data.decode())
                self._process_tcp_message(message, client_socket)
                
        except (ConnectionResetError, json.JSONDecodeError):
            print(f"TCP Client {address} disconnected")
            
        finally:
            
            with self.lock:
                if client_socket in self.connected_clients:
                    self.connected_clients.remove(client_socket)
                
            client_socket.close()
            
    # TCP messsages
    def _process_tcp_message(self, message, client_socket):
        
        msg_type = message.get("type")
        
        # Call helper functions based on message type
        if msg_type == "timer_control":
            self._handle_timer_control(message)
            
        elif msg_type == "calendar_event":
            self._handle_calendar_event(message)
            
        elif msg_type == "goal_update":
            self._handle_goal_update(message)
            
        elif msg_type == "request_sync":
            self._send_sync_data(client_socket)
            
    # Timer state control
    def _handle_timer_control(self, message):
        
        action = message.get("action")
        
        if action == "start":
            with self.lock:
                self.pomoTimer_state["running"] = True
                self.pomoTimer_state["start_time"] = time.time()
            
        elif action == "stop":
            with self.lock:
                self.pomoTimer_state["running"] = False
            
        elif action == "reset":
            with self.lock:
                self.pomoTimer_state = {
                    "running": False, 
                    "start_time": None, 
                    "duration": message.get("duration", 25*60)
                }
        
        # Broadcast timer state to all clients
        self._broadcast_tcp_message({
            "type": "timer_update",
            "timer_state": self.pomoTimer_state
        })
        
    # Broadcast TCP messages to clients (users)
    def _broadcast_tcp_message(self, message):
        
        message_json = json.dumps(message)
        disconnected_clients = []
        
        with self.lock:
            for client in self.connected_clients:
                
                try:
                    
                    client.send(message_json.encode())
                
                except (BrokenPipeError, ConnectionResetError):
                    disconnected_clients.append(client)
            
            for client in disconnected_clients:
                self.connected_clients.remove(client)
    
    # Broadcast UDP messages to clients (users)
    def _broadcast_udp_message(self, message, udp_socket):
        
        message_json = json.dumps(message)
        
        with self.lock:
            for client_addr in self.udp_clients:
                
                try:
                    udp_socket.sendto(message_json.encode(), client_addr)
                
                except:
                    pass
                
    # Syncing data to clients (users)
    def _send_sync_data(self, client_socket):
        
        sync_data = {
            "type": "sync_data",
            "timer_state": self.pomoTimer_state,
            "calendar_events": self.calendar_events
        }
        
        client_socket.send(json.dumps(sync_data).encode())
    
    # Handling calendar events (CRUD)
    def _handle_calendar_event(self, message):
        
        event = message.get("event")
        event["id"] = len(self.calendar_events) + 1
        event["created_at"] = datetime.now().isoformat()
        
        with self.lock:
            self.calendar_events.append(event)
        
        # Broadcast new event to all clients
        self._broadcast_tcp_message({
            "type": "calendar_update",
            "event": event,
            "all_events": self.calendar_events
        })
    
    # Handling goal events (CRUD)
    def _handle_goal_update(self, message):
        
        self._broadcast_tcp_message({
            "type": "goal_update",
            "goal": message.get("goal"),
            "user": message.get("user"),
            "completed": message.get("completed", False)
        })
    
    # Timer updates
    def _manage_timer(self):
        
        while True:
            with self.lock:
                if self.pomoTimer_state["running"]:
                    
                    elapsed = time.time() - self.pomoTimer_state["start_time"]
                    remaining = max(0, self.pomoTimer_state["duration"] - elapsed)
                    
                    # Broadcast timer update every second
                    self._broadcast_tcp_message({
                        "type": "timer_tick",
                        "remaining_time": remaining,
                        "timer_state": self.pomoTimer_state
                    })
                    
                    # Check if timer completed
                    if remaining <= 0:
                        
                        self.pomoTimer_state["running"] = False
                        
                        self._broadcast_tcp_message({
                            "type": "timer_complete",
                            "timer_state": self.pomoTimer_state
                        })
            
            time.sleep(1)

    def _stop_server(self):
        with self.lock:
            for client in self.connected_clients:
                try:
                    client.close()
                except:
                    pass
            
            if self.udp_socket:
                try:
                    self.udp_socket.close()
                except:
                    pass
                
if __name__ == "__main__":
    server = PlatformServer()
    server.start_server()