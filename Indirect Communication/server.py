import socket
import threading
import json
import time
from datetime import datetime
from queue import Queue, Empty

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
        self.shutdown_event = threading.Event()
        self.broadcast_q = Queue()
        self.clients_lock = threading.Lock()
    
    # Starting the central server
    def start_server(self):
        
        print("Starting platform server...")
        
        # TCP
        tcp_thread = threading.Thread(target=self._start_tcp_server, daemon=True)
        tcp_thread.start()
        
        # UDP
        udp_thread = threading.Thread(target=self._start_udp_server, daemon=True)
        udp_thread.start()

        # Timer
        self._timer_thread = threading.Thread(target=self._manage_timer, kwargs={"interval": 1.0}, daemon=True)
        self._timer_thread.start()
        
        # Sender
        self._sender_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._sender_thread.start()
        
        try:
            
            while True:
                
                time.sleep(1)
        
        except KeyboardInterrupt:
            print("\nKeyboard input detected.\nStopping server...")
            self._stop_server() 
    
    # TCP helper
    def _start_tcp_server(self):
        
        # TCP Socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_socket:
            
            tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            tcp_socket.bind((self.host, self.tcp_port))
            tcp_socket.listen(5)
            
            print(f"TCP server listening on {self.host}:{self.tcp_port}")
            
            while not self.shutdown_event.is_set():
                
                client_socket, address = tcp_socket.accept()
                
                print(f"TCP Connection established with address: {address}")
                
                with self.clients_lock:
                    self.connected_clients.append(client_socket)
                
                t = threading.Thread(target=self._handle_tcp_client, args=(client_socket, address), daemon=True)
                
                t.start()
    
    # UDP Helper
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

                    self._broadcast_udp_message(message, self.udp_socket)

                except OSError:
                    pass
        finally:
            try:
                self.udp_socket.close()
            except:
                pass

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
            
            with self.clients_lock:
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
        
        self.broadcast_q.put(message)
        
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
        try:
            client_socket.sendall((json.dumps(sync_data) + "\n").encode("utf-8"))
        except Exception:
            pass
    
    # Handling calendar events (CRUD)
    def _handle_calendar_event(self, message):
        incoming = message.get("event", {})
        
        with self.lock:
                
            event = dict(incoming)
            event["id"] = len(self.calendar_events) + 1
            event["created_at"] = datetime.now().isoformat()
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
    def _manage_timer(self, interval: float = 1.0):
        
        i = 0
        while not self.shutdown_event.is_set():
            
            self.broadcast_q.put({"type": "tick", "i": i, "t": time.time()})
            i += 1

            # timer state updates
            with self.lock:
                
                running = self.pomoTimer_state["running"]
                start = self.pomoTimer_state["start_time"]
                dur = self.pomoTimer_state["duration"]

            if running and start is not None:
                
                elapsed = time.time() - start
                remaining = max(0, dur - elapsed)

                # enqueue, don't send directly
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

            time.sleep(interval)

    # Takes all messages from the queue and sends it to connected clients
    def _send_loop(self):
        
        while not self.shutdown_event.is_set():
            
            # Getting each message from the queue
            try:
                message = self.broadcast_q.get(timeout=0.25)
                
            except Empty:
                continue
            
            try:
                
                # creating the wire to send to the clients
                wire = (json.dumps(message) + "\n").encode("utf-8")
                
                with self.clients_lock:
                    clients = list(self.connected_clients)
                
                # sending each wire to the clients
                for sock in clients:
                    
                    try:
                        sock.sendall(wire)
                    
                    # removing the clients
                    except Exception:
                        with self.clients_lock:
                            if sock in self.connected_clients:
                                self.connected_clients.remove(sock)
                                
            finally:
                self.broadcast_q.task_done()
    
    # Proper shutdown of the
    def _stop_server(self):
        
        self.shutdown_event.set()

        
        for t in [
            getattr(self, "_timer_thread", None),
            getattr(self, "_sender_thread", None),
        ]:
            
            if t:
                t.join(timeout=2)

        with self.clients_lock:
            
            for c in list(self.connected_clients):
                
                try: c.close()
                except: pass
                
            self.connected_clients.clear()

        if self.udp_socket:
            
            try: self.udp_socket.close()
            except: pass
                
if __name__ == "__main__":
    server = PlatformServer()
    server.start_server()