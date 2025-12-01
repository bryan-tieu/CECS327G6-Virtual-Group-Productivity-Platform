# client.py
import socket
import threading
import json
import time
import math
from queue import Queue, Empty
from typing import Optional, Tuple, List, Dict, Any

time_until_suspicion = 5
default_timer_length = 25.0 * 60
maximum_children = 3
tick_rate = 0.1

class PlatformClient:
    def __init__(self, server='localhost', server_port=8000, host='127.0.0.1', p2p_port=8001):
        self.host = host
        self.server = server
        self.server_port = server_port
        self.p2p_port = p2p_port
        
        # Initialize server_socket
        self.server_socket: Optional[socket.socket] = None
        self.running = True
        self.active_input = False
        self.timer_running = False
        self.sync_master: Optional[socket.socket] = None
        self.sync_master_address: Optional[str] = None
        self.sync_grandmaster: Optional[str] = None
        self.children: List[Tuple[str, int, socket.socket, float]] = []
        self.applicants = Queue()
        self.children_lock = threading.Lock()
        self.last_sync: Optional[float] = None
        self.time_left: float = 0.0
        self.inbox = Queue()
        self.inbox_lock = threading.Lock()
        self.server_connected = False
        self.last_requested: Optional[float] = None
        self.lamport_clock = 0
        self.current_tx_id: Optional[str] = None

        # Threading events
        self.stop_event = threading.Event()
        self.tcp_socket: Optional[socket.socket] = None

        # Start tcp listener
        tcp_listen_thread = threading.Thread(target=self.tcp_listener, daemon=True)
        tcp_listen_thread.start()

        # Timer management thread
        timer_thread = threading.Thread(target=self._manage_timer, daemon=True)
        timer_thread.start()

        # Start tcp server
        tcp_thread = threading.Thread(target=self._start_p2p_server, daemon=True)
        tcp_thread.start()

    def connect_servers(self):
        # Attempt server connection
        try:
            print("Attempting TCP server connection...")
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.connect((self.server, self.server_port))
        except Exception as e:
            print(f"[Client] Connection failed: {e}")
            self.server_socket = None
        else:
            print(f"[Client] Connected to server at {self.server}:{self.server_port}")
            self.server_connected = True

    def _start_p2p_server(self):
        # TCP Socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_socket:
            tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            tcp_socket.bind((self.host, self.p2p_port))
            tcp_socket.listen(maximum_children ** 2)

            print(f"TCP server listening on {self.host}:{self.p2p_port}")

            while self.running:
                client_socket, addr = tcp_socket.accept()
                self.applicants.put((addr, client_socket))
                t = threading.Thread(target=self._handle_p2p_client, args=(client_socket, addr), daemon=True)
                t.start()

    def _handle_p2p_client(self, client_socket, address):
        buffer = b""
        try:
            while True:
                data = client_socket.recv(1024)
                if not data:
                    break
                buffer += data

                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line:
                        continue

                    message = json.loads(line.decode("utf-8"))

                    if "lamport" in message:
                        self.lamport_receive(message["lamport"])
                        print(f"[Lamport={self.lamport_clock}] Updated clock from message")

                    msg_type = message.get("type")
                    if msg_type in ("join_request", "suspect_crash"):
                        self._handle_applicants(message)
                    else:
                        self.inbox.put(message)

        except (ConnectionResetError, json.JSONDecodeError):
            print(f"TCP Client {address} disconnected")
        finally:
            with self.children_lock:
                for child in self.children:
                    if child[0] == address:
                        self.children.remove(child)
                        break

            client_socket.close()

    def tcp_listener(self):
        buffer = b""
        while True:
            if self.server_connected and self.server_socket:
                try:
                    data = self.server_socket.recv(1024)
                    if not data:
                        break
                    buffer += data

                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        if not line:
                            continue

                        try:
                            message = json.loads(line.decode("utf-8"))
                            if "lamport" in message:
                                self.lamport_receive(message["lamport"])
                        except Exception as e:
                            print(f"[Client] JSON parse error: {e}")
                            continue
                        
                        if not self.active_input or message.get("type") != "tick":
                            self.handle_server_message(message)

                except Exception as e:
                    print(f"[Client] TCP listener error: {e}")
            else:
                time.sleep(1)  # Sleep if not connected

    def handle_server_message(self, msg):
        self.lamport_event()
        msg_type = msg.get("type")

        if msg_type == "timer_update":
            print(f"[Server] Timer State Updated: {msg['timer_state']}")

        elif msg_type == "timer_tick":
            if not self.active_input:
                mins, secs = divmod(int(msg["remaining_time"]), 60)
                print(f"\r[Timer] Remaining: {mins:02d}:{secs:02d}   ", end="", flush=True)

        elif msg_type == "timer_complete":
            print("[Timer] Pomodoro session complete")
        
        elif msg_type == "tx_started":
            self.current_tx_id = msg["tx_id"]
            self._print_tx_event(msg["tx_id"], "Began transaction")

        elif msg_type == "tx_op_ok":
            self._print_tx_event(msg["tx_id"], "Operation recorded")
            self.active_input = True

        elif msg_type == "tx_committed":
            self._print_tx_event(msg["tx_id"], "Commit successful")
            if self.current_tx_id == msg["tx_id"]:
                self.current_tx_id = None
            self.active_input = True

        elif msg_type == "tx_aborted":
            self._print_tx_event(msg["tx_id"], "Aborted", msg.get("reason"))
            if self.current_tx_id == msg["tx_id"]:
                self.current_tx_id = None
            self.active_input = True

        elif msg_type == "tx_error":
            self._print_tx_event(msg.get("tx_id"), "Error", msg.get("reason"))
            self.active_input = True

        elif msg_type == "tx_debug_info":
            print("\n--- Transaction Debug Info ---")

            txs = msg.get("transactions", [])
            if not txs:
                print("No transactions recorded.")
            else:
                print("\n-- Transactions --")
                for tx in txs:
                    me_flag = "[ME]" if tx.get("is_mine") else "[OTHER]"
                    print(f"{me_flag} TX {tx['tx_id']} [{tx['state']}] ops={tx['num_ops']}")
                    for op in tx.get("ops", []):
                        print(f"   - {op.get('op_type')} {op.get('payload')}")

            locks = msg.get("locks", [])
            if not locks:
                print("\n-- Locks --")
                print("No locks currently held.")
            else:
                print("\n-- Locks --")
                for lock in locks:
                    me_flag = "[ME]" if lock.get("owned_by_me") else "[OTHER]"
                    print(f"{me_flag} {lock['resource']} held by TX {lock['tx_id']}")

            print("--- End Transaction Debug Info ---")
            self.active_input = True

        else:
            if self.active_input:
                print(f"[Server] Message: {msg}")

    def _print_tx_event(self, tx_id, status, reason=None):
        if tx_id is None:
            prefix = "[TX ?]"
        else:
            prefix = f"[TX {tx_id}]"

        if reason:
            print(f"{prefix} {status}: {reason}")
        else:
            print(f"{prefix} {status}")

    def send_tcp_message(self, msg, sock: Optional[socket.socket]):
        try:
            if sock is None:
                print(f"[Client] Cannot send message, socket is None")
                return
                
            msg["lamport"] = self.lamport_send()
            wire = (json.dumps(msg) + "\n").encode("utf-8")
            sock.sendall(wire)
            msg_type = msg.get("type")
            if msg_type in ("tx_op", "tx_commit", "tx_abort"):
                print(f"[TX {msg.get('tx_id')}] Sent {msg_type} (Lamport={msg['lamport']})")
        except Exception as e:
            print(f"[Client] Error sending tcp message: {e}")

    def start_timer(self, duration=default_timer_length):
        self.lamport_event()
        if self.timer_running:
            self.stop_timer()

        self.sync_master = None
        self.sync_master_address = None
        self.time_left = duration
        self.timer_running = True

    def join_timer(self, address: str, seamless=False):
        self.lamport_event()
        if self.timer_running and not seamless:
            self.stop_timer()

        msg = {"type": "join_request", "address": self.host}
        self.sync_master = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if not seamless:
            print(f"Attempting to connect to {address} on port {self.p2p_port}")
        
        self.last_sync = time.time()
        try:
            self.sync_master.connect((address, self.p2p_port))
        except Exception as e:
            print(f"[Client] Connection failed: {e}")
            self.lamport_event()
            if self.sync_master:
                self.sync_master.close()
                self.sync_master = None
        else:
            if not seamless:
                print(f"[Client] Connected to server at {address}:{self.p2p_port}, sending join request")
            self.send_tcp_message(msg, self.sync_master)
            self.sync_master_address = address

        self.join_reply_wait()

    def join_reply_wait(self, timeout=5):
        if self.sync_master is None:
            print("No sync master to wait for reply")
            return
            
        start = time.time()
        buffer = b""
        self.sync_master.settimeout(0.1)

        while time.time() - start < timeout:
            try:
                data = self.sync_master.recv(1024)
                if not data:
                    continue
                    
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line:
                        continue
                    message = json.loads(line.decode("utf-8"))

                    if "lamport" in message:
                        self.lamport_receive(message["lamport"])

                    msg_type = message.get("type")
                    if msg_type == "confirm_join":
                        print("Join confirmed")
                        self.sync_grandmaster = message.get("parent_address")
                        self.timer_running = True
                        return
                    elif msg_type == "deny_join":
                        print("Join denied... trying another")
                        self.sync_master_address = None
                        return
                    
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error receiving join reply: {e}")
                break

        print("\nNo reply received... join timed out.")

    def stop_timer(self):
        self.lamport_event()
        
        # 1. Notify server to stop timer
        if self.server_socket and self.server_connected:
            msg = {"type": "timer_control", "action": "stop"}
            self.send_tcp_message(msg, self.server_socket)
            print("[Client] Sent stop command to server")
        
        # 2. Existing P2P cleanup
        if self.sync_master is None and self.timer_running:
            self._promotion()
        elif self.timer_running and self.sync_master:
            msg = {"type": "disconnect_notice", "address": self.host}
            self.send_tcp_message(msg, self.sync_master)
            self.sync_master.close()
            self.sync_master = None

        # 3. State cleanup
        self.time_left = 0.0
        with self.children_lock:
            for child in self.children:
                child[2].close()
            self.children = []
        
        self.sync_master = None
        self.sync_master_address = None
        self.sync_grandmaster = None
        self.timer_running = False
        print("[Timer] Stopped completely")

    def _request_sync(self):
        if self.sync_master is None:
            return
            
        lineage = 1
        with self.children_lock:
            for child in self.children:
                lineage += child[1]

        msg = {"type": "sync_request", "lineage": lineage}
        self.send_tcp_message(msg, self.sync_master)
        self.last_requested = time.time()

    def _manage_timer(self):
        crash_suspected = False
        last_tick: Optional[float] = None
        response_timer: float = 0.0

        while True:
            start_time = time.time()
            if self.timer_running:
                # Update internal timer
                current = time.time()
                if last_tick is not None:
                    time_diff = current - last_tick
                    self.time_left = max(0, self.time_left - time_diff)
                    if crash_suspected:
                        response_timer += time_diff
                last_tick = time.time()
                
                if self.time_left <= 0:
                    self.lamport_event()
                    print("Timer finished")
                    self.stop_timer()

                if self.sync_master is not None:
                    if self.last_sync is not None and time.time() - self.last_sync > time_until_suspicion:
                        crash_suspected = True
                        self.lamport_event()
                    else:
                        self._request_sync()

                if crash_suspected:
                    if response_timer > 0:
                        if response_timer > time_until_suspicion:
                            self.sync_grandmaster = None
                    elif self.sync_grandmaster is None:
                        self.lamport_event()
                        print("Synced timer unresponsive, reverting to local timer.")
                        self.start_timer(self.time_left)
                        continue
                    else:
                        if self.sync_master:
                            msg = {"type": "disconnect_notice", "address": self.host}
                            self.send_tcp_message(msg, self.sync_master)
                            self.sync_master.close()
                            self.sync_master_address = None

                        temp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        try:
                            temp.connect((self.sync_grandmaster, self.p2p_port))
                            self.send_tcp_message({"type": "suspect_crash", "address": self.host}, temp)
                            temp.close()
                        except Exception as e:
                            print(f"Synced timer became unresponsive, unable to relink with network: {e}")

                # Monitor children for failure
                with self.children_lock:
                    for child in self.children:
                        if child[3] > time_until_suspicion * 2:
                            self.lamport_event()
                            msg = {"type": "disconnect_notice", "address": self.host}
                            self.send_tcp_message(msg, child[2])
                            child[2].close()
                            self.children.remove(child)

                # Check for messages and respond accordingly
                while True:
                    try:
                        message = self.inbox.get(block=False, timeout=tick_rate)
                    except Empty:
                        break

                    msg_type = message.get("type")

                    if msg_type == "sync_request":
                        requester = message.get("address")
                        selected: Optional[socket.socket] = None
                        with self.children_lock:
                            for child in self.children:
                                if child[0] == requester:
                                    selected = child[2]
                                    break
                        if selected is not None:
                            reply = {"type": "sync_update", "time": self.time_left, "grandparent": self.sync_grandmaster}
                            self.send_tcp_message(reply, selected)

                    elif msg_type == "sync_update":
                        self.lamport_receive(message["lamport"])
                        self.lamport_event()
                        received = time.time()
                        try:
                            if self.last_requested is not None:
                                self.time_left = message["time"] - (received - self.last_requested)/2
                                self.sync_grandmaster = message.get("grandparent")
                                self.last_sync = received
                        except (TypeError, KeyError):
                            print("Syncing error: Update was received without being requested")

                    elif msg_type in ("join_request", "suspect_crash"):
                        self._handle_applicants(message)

                    elif msg_type == "update_parent":
                        self.lamport_event()
                        address = message.get("address")
                        if address:
                            self.join_timer(address, seamless=True)

                    elif msg_type == "disconnect_notice":
                        sender = message.get("address")
                        if sender == self.sync_master_address:
                            self.lamport_event()
                            if self.sync_master_address:
                                self.join_timer(self.sync_master_address, seamless=True)
                        else:
                            with self.children_lock:
                                for child in self.children:
                                    if sender == child[0]:
                                        self.lamport_event()
                                        child[2].close()
                                        self.children.remove(child)
                                        break

                    elif msg_type == "promotion":
                        self.lamport_event()
                        self._promotion()
                        if self.sync_grandmaster is None:
                            self.sync_master = None
                            self.sync_master_address = None

            time.sleep(max(0, tick_rate - (time.time() - start_time)))

    def _promotion(self):
        self.lamport_event()
        n = math.inf
        selected_child = None
        selected_socket: Optional[socket.socket] = None
        
        with self.children_lock:
            if self.children:
                for child in self.children:
                    if child[1] < n:
                        n = child[1]
                        selected_child = child
                        selected_socket = child[2]

                if selected_child:
                    self.children.remove(selected_child)

                    if selected_socket:
                        msg = {"type": "promotion"}
                        self.send_tcp_message(msg, selected_socket)

                        msg = {"type": "update_parent", "address": selected_child[0]}
                        for child in self.children:
                            self.send_tcp_message(msg, child[2])

    def _handle_applicants(self, initial):
        message_list = [initial]
        while True:
            try:
                n = self.inbox.get(block=False)
                message_list.append(n)
            except Empty:
                break

        for message in message_list:
            msg_type = message.get("type")
            if msg_type not in ("suspect_crash", "join_request"):
                self.inbox.put(message)

        while True:
            try:
                applicant = self.applicants.get_nowait()
                for message in message_list:
                    sender = message.get("address")
                    if applicant[0][0] == sender:
                        if message.get("type") == "suspect_crash":
                            self._suspected_crash(message, applicant)
                        elif message.get("type") == "join_request":
                            applicant_sock = applicant[1]
                            self._join_request(applicant, applicant_sock)
                        break
            except Empty:
                break

    def _suspected_crash(self, message, applicant):
        suspect = message.get("suspect")
        action_taken = False
        
        with self.children_lock:
            for child in self.children:
                if child[0] == suspect:
                    if child[3] > time_until_suspicion / 2:
                        msg = {"type": "disconnect_notice", "address": self.host}
                        self.send_tcp_message(msg, child[2])
                        child[2].close()
                        self.children.remove(child)
                        action_taken = True
                        break
            
            if action_taken:
                msg = {"type": "update_parent", "address": self.host}
            else:
                suitable_replacement = self.host
                n = math.inf
                for child in self.children:
                    if child[1] < n:
                        suitable_replacement = child[0]
                        n = child[1]

                msg = {"type": "update_parent", "address": suitable_replacement}
        
        self.lamport_event()
        self.send_tcp_message(msg, applicant[1])

    def _join_request(self, applicant, applicant_sock):
        if len(self.children) < maximum_children:
            parent_addr = self.sync_master_address if self.sync_master_address else self.host
            reply = {"type": "confirm_join", "parent_address": parent_addr}
            with self.children_lock:
                self.children.append((applicant[0][0], 0, applicant_sock, time.time()))
            self.lamport_event()
        else:
            reply = {"type": "deny_join", "address": self.min_lineage()[0]}
            self.lamport_event()

        self.send_tcp_message(reply, applicant_sock)

    def min_lineage(self):
        n = math.inf
        selected_child = None
        
        with self.children_lock:
            for child in self.children:
                if child[1] < n:
                    selected_child = child
                    n = child[1]
        
        return selected_child or (None, None, None, None)

    # Lamport clock methods
    def lamport_event(self):
        self.lamport_clock += 1

    def lamport_send(self):
        self.lamport_clock += 1
        return self.lamport_clock
    
    def lamport_receive(self, recv_timestamp):
        self.lamport_clock = max(self.lamport_clock, recv_timestamp) + 1

    # Transactions
    def begin_transaction(self):
        self.lamport_event()
        msg = {"type": "tx_begin"}
        self.send_tcp_message(msg, self.server_socket)

    def request_tx_debug(self):
        self.active_input = False
        msg = {"type": "tx_debug"}
        self.send_tcp_message(msg, self.server_socket)

    def commit_transaction(self):
        if self.current_tx_id is None:
            print("No active transaction.")
            return
        msg = {"type": "tx_commit", "tx_id": self.current_tx_id}
        self.send_tcp_message(msg, self.server_socket)

    def abort_transaction(self):
        if self.current_tx_id is None:
            return
        msg = {"type": "tx_abort", "tx_id": self.current_tx_id}
        self.send_tcp_message(msg, self.server_socket)
        self.current_tx_id = None

    def tx_add_calendar_event(self, title, description, time_str):
        if self.current_tx_id is None:
            print("No active transaction. Start one first.")
            return
        payload = {"title": title, "description": description, "scheduled_time": time_str}
        msg = {"type": "tx_op", "tx_id": self.current_tx_id, "op_type": "calendar_event", "payload": payload}
        self.send_tcp_message(msg, self.server_socket)

    def tx_update_goal(self, goal, user, completed=False):
        if self.current_tx_id is None:
            print("No active transaction. Start one first.")
            return
        payload = {"goal": goal, "user": user, "completed": completed}
        msg = {"type": "tx_op", "tx_id": self.current_tx_id, "op_type": "goal_update", "payload": payload}
        self.send_tcp_message(msg, self.server_socket)

if __name__ == "__main__":
    client = PlatformClient()
    client.connect_servers()
    client.active_input = True
    
    while True:
        if not client.running:
            break
        if not client.active_input:
            time.sleep(0.1)
            continue

        print("\nCommand Options (Enter number):\n"
        "1. Start Timer\n"
        "2. Stop Timer (Local + Server)\n"
        "3. Join Timer\n"
        "4. Begin Transaction\n"
        "5. List Transactions / Locks\n"
        "0. Exit\n")
            
        option = input("Select Option: ")

        if option == "1":
            client.start_timer()
        elif option == "2":
            client.stop_timer()
        elif option == "3":
            address = input("Enter address: ")
            client.join_timer(address)
        elif option == "4":
            client.begin_transaction()
            start_wait = time.time()
            while client.current_tx_id is None and time.time() - start_wait < 2:
                time.sleep(0.05)

            if client.current_tx_id is None:
                print("Failed to start transaction (no response from server).")
                continue

            while True:
                while not client.active_input:
                    if client.current_tx_id is None:
                        print("\nTransaction is no longer active (aborted or timed out). Returning to main menu.")
                        break
                    time.sleep(0.05)
                
                if client.current_tx_id is None:
                    break

                print("\nTransaction Menu:\n"
                      "1. Add Calendar Event \n"
                      "2. Update Goal \n"
                      "3. Commit Transaction\n"
                      "4. Abort Transaction\n")
                client.active_input = True

                tx_option = input("Select an option: ")

                if tx_option == "1":
                    title = input("Title: ")
                    desc = input("Description: ")
                    time_str = input("Time (YYYY-MM-DD HH:MM): ")
                    client.active_input = False
                    client.tx_add_calendar_event(title, desc, time_str)
                elif tx_option == "2":
                    user = input("User: ")
                    goal = input("Goal: ")
                    finish = input("Completed? (y/n): ").strip().lower() == "y"
                    client.active_input = False
                    client.tx_update_goal(goal, user, finish)
                elif tx_option == "3":
                    client.commit_transaction()
                    client.active_input = False
                    break
                elif tx_option == "4":
                    client.abort_transaction()
                    client.active_input = False
                    break
                else:
                    print("Invalid input...")

            if client.current_tx_id is None:
                client.active_input = True
        elif option == "5": 
            client.request_tx_debug()
            client.active_input = False
        elif option == "0":
            print("Exiting...")
            client.running = False
            
            client.stop_event.set()
            
            # Close sockets safely
            if client.server_socket:
                client.server_socket.close()
            
            if client.sync_master:
                client.sync_master.close()
            
            # Stop timer
            client.stop_timer()
            break
        else:
            print("Invalid input...")