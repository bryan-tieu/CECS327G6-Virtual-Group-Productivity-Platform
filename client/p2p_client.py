# client/p2p_client.py
import socket
import threading
import json
import time
import math
from queue import Queue, Empty
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class P2PClient:

    def __init__(self, client_id="user", server_host='localhost', server_port=8000, 
                 p2p_host='localhost', p2p_port=8001):
        self.client_id = client_id
        self.server_host = server_host
        self.server_port = server_port
        self.p2p_host = p2p_host
        self.p2p_port = p2p_port
        
        #  Connection state
        self.server_socket = None
        self.server_connected = False
        self.p2p_connected = False
        
        #  P2P network state
        self.sync_master = None
        self.sync_master_address = None
        self.sync_grandmaster = None
        self.children = []  #  [address, lineage, socket, last_contact]
        self.applicants = Queue()
        self.children_lock = threading.Lock()
        
        #  Timer state
        self.timer_running = False
        self.time_left = 0.0
        self.last_sync = time.time()
        self.last_requested = time.time()
        self.active_input = False
        
        #  Concurrency
        self.inbox = Queue()
        self.inbox_lock = threading.Lock()
        self.running = True
        
        #  Configuration
        self.time_until_suspicion = 5
        self.default_timer_length = 25.0 * 60
        self.maximum_children = 3
        self.tick_rate = 0.1
        
        #  Start all services
        self._initialize_services()

    def _initialize_services(self):
        #  Start all client services
        logger.info(f"Initializing P2P Client {self.client_id}...")
        
        services = [
            threading.Thread(target=self._server_listener, daemon=True, name="Server-Listener"),
            threading.Thread(target=self._p2p_server, daemon=True, name="P2P-Server"),
            threading.Thread(target=self._hybrid_timer_manager, daemon=True, name="Hybrid-Timer"),
            threading.Thread(target=self._status_monitor, daemon=True, name="Status-Monitor")
        ]
        
        for service in services:
            service.start()
        
        #  Connect to central server
        self.connect_to_server()

    def connect_to_server(self):
        #  Connect to central server
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.connect((self.server_host, self.server_port))
            self.server_connected = True
            
            logger.info(f"Connected to central server at {self.server_host}:{self.server_port}")
            
            self._send_to_server({
                "type": "client_hello",
                "client_id": self.client_id,
                "p2p_capable": True,
                "p2p_port": self.p2p_port
            })
            
        except Exception as e:
            logger.info("Operating in P2P-only mode")

    def _server_listener(self):
        #  Listen for messages from central server
        buffer = b""
        while self.running:
            if not self.server_connected or self.server_socket is None:
                time.sleep(1)
                continue
                
            try:
                data = self.server_socket.recv(1024)
                if not data:
                    break
                    
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line:
                        message = json.loads(line.decode("utf-8"))
                        self._handle_server_message(message)
                        
            except Exception as e:
                logger.error(f"Server connection error: {e}")
                self.server_connected = False
                if self.server_socket:
                    self.server_socket.close()
                    self.server_socket = None

    def _handle_server_message(self, message):
        #  Process messages from central server
        msg_type = message.get("type")
        
        if msg_type == "timer_update":
            logger.info("[Server] Timer state updated")
            if not self.timer_running:
                self._sync_with_server_timer(message["timer_state"])
                
        elif msg_type == "timer_tick":
            if not self.timer_running and not self.active_input:
                mins, secs = divmod(int(message["remaining_time"]), 60)
                print(f"\r[Server Timer] {mins:02d}:{secs:02d}   ", end="", flush=True)
                
        elif msg_type == "calendar_update":
            logger.info(f"[Server] New calendar event: {message['event']['title']}")
            
        elif msg_type == "p2p_acknowledge":
            logger.info("[Server] P2P capability acknowledged")

    def _p2p_server(self):
        #  Start P2P server for decentralized coordination
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_socket:
            tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            tcp_socket.bind((self.p2p_host, self.p2p_port))
            tcp_socket.listen(self.maximum_children ** 2)

            logger.info(f"P2P server listening on {self.p2p_host}:{self.p2p_port}")

            while self.running:
                try:
                    client_socket, addr = tcp_socket.accept()
                    self.applicants.put((addr, client_socket))
                    
                    threading.Thread(
                        target=self._handle_p2p_client, 
                        args=(client_socket, addr), 
                        daemon=True
                    ).start()
                    
                except Exception as e:
                    if self.running:
                        logger.error(f"P2P server error: {e}")

    def _handle_p2p_client(self, client_socket, address):
        #  Handle incoming P2P connection
        try:
            while True:
                data = client_socket.recv(1024)
                if not data:
                    break

                message = json.loads(data.decode())
                logger.info(f"P2P message from {address}: {message.get('type')}")
                
                with self.inbox_lock:
                    self.inbox.put(message)

        except (ConnectionResetError, json.JSONDecodeError) as e:
            logger.info(f"P2P Client {address} disconnected: {e}")
        finally:
            with self.children_lock:
                for child in self.children:
                    if child[0] == address:
                        self.children.remove(child)
                        break
            client_socket.close()

    def _hybrid_timer_manager(self):
        crash_suspected = False
        last_tick: float = time.time()
        response_timer = 0.0  #  Ensure float type

        while self.running:
            start_time = time.time()
            
            if self.timer_running:
                #  Update internal timer with type safety
                current = time.time()
                if last_tick is not None:
                    time_diff = current - last_tick
                    self.time_left = max(0, self.time_left - time_diff)
                    if crash_suspected:
                        response_timer += time_diff
                last_tick = current
                
                if self.time_left <= 0:
                    logger.info("Timer finished!")
                    self._handle_timer_completion()
                    
                if self.sync_master is not None:  #  Using P2P
                    if time.time() - self.last_sync > self.time_until_suspicion:
                        crash_suspected = True
                        logger.warning("P2P sync delayed, considering fallback...")
                    else:
                        self._request_p2p_sync()
                        
                elif self.server_connected:  #  Using server fallback
                    if time.time() - self.last_sync > 10:
                        self._request_server_sync()
                
                #  Handle P2P failure
                if crash_suspected and self.sync_master:
                    self._handle_p2p_failure()
                    
                #  Process messages
                self._process_inbox_messages()
                
            else:
                #  Handle coordination when no timer running
                self._process_inbox_messages()
                
                #  Cleanup stale connections
                if (self.sync_master and 
                    time.time() - self.last_sync > self.time_until_suspicion):
                    logger.info("Cleaning up stale P2P connection")
                    self.sync_master.close()
                    self.sync_master = None

            time.sleep(max(0, self.tick_rate - (time.time() - start_time)))

    def _process_inbox_messages(self):
        #  Process all messages in inbox
        while True:
            try:
                message = self.inbox.get(block=False)
                self._handle_p2p_message(message)
            except Empty:
                break

    def _handle_p2p_message(self, message):
        #  Handle P2P protocol messages
        msg_type = message.get("type")
        
        if msg_type == "sync_request":
            self._handle_sync_request(message)
        elif msg_type == "sync_update":
            self._handle_sync_update(message)
        elif msg_type == "join_request":
            self._handle_join_request(message)
        elif msg_type == "confirm_join":
            self._handle_confirm_join(message)
        elif msg_type == "deny_join":
            self._handle_deny_join(message)
        elif msg_type == "promotion":
            self._handle_promotion(message)
        elif msg_type == "update_parent":
            self._handle_update_parent(message)
        elif msg_type == "disconnect_notice":
            self._handle_disconnect_notice(message)

    def _handle_sync_request(self, message):
        #  Handle sync request from child
        requester = message.get("address")
        with self.children_lock:
            for child in self.children:
                if child[0] == requester:
                    selected = child[2]
                    break
        
        if selected:
            reply = {
                "type": "sync_update",
                "time": self.time_left,
                "grandparent": self.sync_grandmaster
            }
            self._send_p2p_message_direct(reply, selected)

    def _handle_sync_update(self, message):
        #  Handle sync update from master
        received = time.time()
        try:
            self.time_left = message["time"] - (received - self.last_requested) / 2
            self.sync_grandmaster = message.get("grandparent")
            self.last_sync = received
            crash_suspected = False
        except TypeError:
            logger.error("Syncing error: Update was received without being requested")

    def _handle_join_request(self, message):
        #  Handle request to join our timer network
        applicant_addr = message.get("address")
        pass

    def _handle_confirm_join(self, message):
        self.sync_grandmaster = message.get("parent_address")
        self.timer_running = True
        logger.info("Joined P2P timer network")

    def _handle_deny_join(self, message):
        #  Handle denial of join request
        new_address = message.get("address")
        logger.info(f"Join denied, trying {new_address} instead")
        self.join_p2p_timer(new_address)

    def _handle_promotion(self, message):
        #  Handle promotion to master
        logger.info("Promoted to master timer")
        self.sync_master = None
        self.sync_master_address = None

    def _handle_update_parent(self, message):
        #  Handle parent update request
        new_parent = message.get("address")
        logger.info(f"Updating parent to {new_parent}")
        self.join_p2p_timer(new_parent, seamless=True)

    def _handle_disconnect_notice(self, message):
        #  Handle disconnect notification
        logger.info("Peer disconnected from our network")

    def _request_p2p_sync(self):
        #  Request sync from P2P master with type safety
        if self.sync_master is None:
            return
            
        lineage = 1
        with self.children_lock:
            for child in self.children:
                lineage += child[1]

        msg = {
            "type": "sync_request",
            "lineage": lineage,
            "address": f"{self.p2p_host}:{self.p2p_port}"
        }
        self._send_p2p_message_direct(msg, self.sync_master)
        self.last_requested = time.time()

    def _request_server_sync(self):
        #  Request sync from server
        if self.server_connected:
            self._send_to_server({
                "type": "request_sync",
                "client_id": self.client_id
            })
            self.last_requested = time.time()

    def _sync_with_server_timer(self, timer_state):
        #  Sync with server timer state
        if timer_state["running"] and timer_state["start_time"]:
            elapsed = time.time() - timer_state["start_time"]
            self.time_left = max(0, timer_state["duration"] - elapsed)
            self.timer_running = True
            self.last_sync = time.time()

    def _handle_timer_completion(self):
        #  Handle timer completion
        logger.info("Timer completed!")
        self.stop_timer()

    def _handle_p2p_failure(self):
        #  Handle P2P master failure
        if self.sync_grandmaster is None:
            logger.warning("Synced timer unresponsive, reverting to local timer.")
            self.start_timer(self.time_left, mode="p2p")
        else:
            logger.warning("Attempting to reconnect through grandmaster...")
            self._send_p2p_message_direct({
                "type": "suspect_crash",
                "address": f"{self.p2p_host}:{self.p2p_port}",
                "suspect": self.sync_master_address
            }, self.sync_grandmaster)

    def _p2p_available(self):
        #  Check if P2P network is available
        return len(self.children) > 0 or self.sync_master is not None

    def start_timer(self, duration=None, mode="p2p"):
        #  Start timer with preferred mode
        if self.timer_running:
            self.stop_timer()

        duration = duration or self.default_timer_length
        
        if mode == "p2p" or (mode == "auto" and self._p2p_available()):
            logger.info("Starting P2P timer (low latency)")
            self._start_p2p_timer(duration)
        else:
            logger.info("Starting server-based timer (reliable)")
            self._start_server_timer(duration)

    def _start_p2p_timer(self, duration):
        #  Start timer in P2P mode
        self.sync_master = None
        self.sync_master_address = None
        self.time_left = duration
        self.timer_running = True
        self.last_sync = time.time()

    def _start_server_timer(self, duration):
        #  Start timer through central server
        self._send_to_server({
            "type": "timer_control",
            "action": "start",
            "duration": duration,
            "client_id": self.client_id
        })

    def stop_timer(self):
        #  Stop the current timer with type safety
        if self.sync_master is not None:
            msg = {
                "type": "disconnect_notice",
                "address": f"{self.p2p_host}:{self.p2p_port}"
            }
            self._send_p2p_message_direct(msg, self.sync_master)
            if self.sync_master:
                self.sync_master.close()

        #  State cleanup
        self.time_left = 0.0
        with self.children_lock:
            self.children = []
        self.sync_master = None
        self.sync_master_address = None
        self.sync_grandmaster = None
        self.timer_running = False
        logger.info("Timer stopped")

    def join_p2p_timer(self, address, seamless=False):
        #  Join existing P2P timer network with type safety
        if self.timer_running and not seamless:
            self.stop_timer()

        logger.info(f"Joining P2P timer at {address}")
        
        try:
            self.sync_master = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            host, port = address.split(":")
            self.sync_master.connect((host, int(port)))
            self.last_sync = time.time()
            
            msg = {
                "type": "join_request",
                "address": f"{self.p2p_host}:{self.p2p_port}",
                "client_id": self.client_id
            }
            self._send_p2p_message_direct(msg, self.sync_master)
            self.sync_master_address = address
            
            if not seamless:
                logger.info(f"Connected to P2P master at {address}")
                
        except Exception as e:
            logger.error(f"Failed to join P2P timer: {e}")
            if self.sync_master:
                self.sync_master.close()
            self.sync_master = None
            self.sync_master_address = None

    def _send_to_server(self, message):
        #  Send message to central server
        #  Early return if socket is None
        if self.server_socket is None:
            logger.debug("Server socket is None, cannot send message")
            return
            
        if not self.server_connected:
            logger.debug("Server not connected, cannot send message")
            return
            
        try:
            wire = (json.dumps(message) + "\n").encode("utf-8")
            self.server_socket.sendall(wire)
        except Exception as e:
            logger.error(f"Failed to send to server: {e}")
            self.server_connected = False
            #  Clean up the socket
            self.server_socket.close()
            self.server_socket = None

    def _send_p2p_message_direct(self, message, sock):
        #  Send message to P2P peer via existing socket with type safety
        if sock is not None:
            try:
                sock.send(json.dumps(message).encode())
            except Exception as e:
                logger.error(f"Failed to send P2P message: {e}")
    
    def _status_monitor(self):
        #  Monitor and report system status
        while self.running:
            time.sleep(10)
            status = {
                "server_connected": self.server_connected,
                "p2p_connected": bool(self.sync_master or self.children),
                "timer_running": self.timer_running,
                "mode": "p2p" if self.sync_master else "server",
                "children_count": len(self.children)
            }
            logger.info(f"Client Status: {status}")

    def _promotion(self):
        n = math.inf
        with self.children_lock:
            if self.children:
                new_children = []
                for child in self.children:
                    new_children.append((child[0], child[1]))
                    n = min(n, child[1])
                    if n == child[1]:
                        selected = child
                        s = child[2]

                new_children.remove((selected[0], n))
                self.children.remove(selected)

                msg = {"type": "promotion"}
                self._send_p2p_message_direct(msg, s)

                msg = {"type": "update_parent", "address": selected[0]}
                for child in self.children:
                    self._send_p2p_message_direct(msg, child[2])

    def _handle_applicant(self):
        #  Handle incoming connection applicants
        pass

    def add_calendar_event(self, title, description, time_str):
        #  Add calendar event via server
        event = {
            "title": title,
            "description": description,
            "scheduled_time": time_str
        }
        self._send_to_server({
            "type": "calendar_event",
            "event": event
        })

    def update_goal(self, goal, user, completed=False):
        #  Update goal via server
        self._send_to_server({
            "type": "goal_update",
            "goal": goal,
            "user": user,
            "completed": completed
        })

    def shutdown(self):
        #  Clean shutdown of client
        self.running = False
        self.stop_timer()
        if self.server_socket:
            self.server_socket.close()
        logger.info("P2P client shutdown complete")


# Demo and test code
if __name__ == "__main__":
    client = P2PClient(client_id="demo_user")
    
    try:
        while True:
            print("\nCommand Options:")
            print("1. Start Timer (P2P)")
            print("2. Start Timer (Server)")
            print("3. Stop Timer")
            print("4. Join P2P Timer")
            print("5. Add Calendar Event")
            print("6. Update Goal")
            print("0. Exit")
            
            option = input("Select Option: ")

            if option == "1":
                client.start_timer(mode="p2p")
            elif option == "2":
                client.start_timer(mode="server")
            elif option == "3":
                client.stop_timer()
            elif option == "4":
                address = input("Enter address (host:port): ")
                client.join_p2p_timer(address)
            elif option == "5":
                title = input("Title: ")
                desc = input("Description: ")
                time_str = input("Time: ")
                client.add_calendar_event(title, desc, time_str)
            elif option == "6":
                user = input("User: ")
                goal = input("Goal: ")
                completed = input("Completed? (y/n): ").lower() == 'y'
                client.update_goal(goal, user, completed)
            elif option == "0":
                break
            else:
                print("Invalid option")
                
    except KeyboardInterrupt:
        pass
    finally:
        client.shutdown()