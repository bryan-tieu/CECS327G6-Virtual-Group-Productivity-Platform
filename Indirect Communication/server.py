import socket
import threading
import json
import time
from datetime import datetime
from queue import Queue, Empty

class PlatformServer:
    
    # Init
    def __init__(self, host='localhost', tcp_port=8000, udp_port = 8001, peers = None, server_id = None, role = "coordinator"):
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

        self.transactions = {} 
        self.next_tx_id = 1
        self.locks = {} # resource key -> tx_id
        
        # 2PC Implementation
        self.server_id = server_id or f"{host}:{tcp_port}"
        self.peers = peers or []

        self.handles_calendar = role in ("coordinator", "calendar")
        self.handles_goals = role in ("coordinator", "goals")
        self.is_coordinator = role in ("coordinator", "tx_only")

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
        
        # Background cleanup
        self.tx_timeout_seconds = 60
        self._tx_cleanup_thread = threading.Thread(
            target=self._cleanup_stale_transactions,
            daemon=True,
        )
        self._tx_cleanup_thread.start()

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
                
        except (ConnectionResetError, ConnectionAbortedError, json.JSONDecodeError):
            print(f"TCP Client {address} disconnected")
            
        finally:
            # Abort any active transactions belonging to this client
            # (this covers normal disconnects AND crashes that result in socket close)
            owned_tx_ids = [
                tx_id
                for tx_id, tx in list(self.transactions.items())
                if tx["client"] is client_socket and tx["state"] == "active"
            ]
            for tx_id in owned_tx_ids:
                # no need to notify: the client is already gone
                self._abort_tx_internal(tx_id, reason="client_disconnect", notify_client=False)

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

        elif msg_type in ("tx_begin", "tx_op", "tx_commit", "tx_abort", "tx_debug"):
            if not self.is_coordinator:
                reply = {"type": "error", "reason": "not_a_coordinator"}
                client_socket.sendall((json.dumps(reply) + "\n").encode("utf-8"))
                return
        
        if msg_type == "tx_begin":
            self._handle_tx_begin(message, client_socket)

        elif msg_type == "tx_op":
            self._handle_tx_op(message, client_socket)

        elif msg_type == "tx_commit":
            self._handle_tx_commit(message, client_socket)

        elif msg_type == "tx_abort":
            self._handle_tx_abort(message, client_socket)
        
        elif msg_type == "tx_debug":
            self._handle_tx_debug(message, client_socket)

        elif msg_type == "tx_prepare":
            self._handle_tx_prepare(message, client_socket)

        elif msg_type == "tx_decision":
            self._handle_tx_decision(message, client_socket)

    
    # Transaction Helpers
    def _handle_tx_begin(self, message, client_socket):
        tx_id = self.next_tx_id
        self.next_tx_id += 1

        print(f"[SERVER] Starting Transaction {tx_id} for client {client_socket.getpeername()}")

        self.transactions[tx_id] = {
            "client": client_socket,
            "ops": [],
            "state": "active",
            "last_activity": time.time(),
        }

        reply = {
            "type": "tx_started",
            "tx_id": tx_id
        }
        client_socket.sendall((json.dumps(reply) + "\n").encode("utf-8"))

    def _handle_tx_op(self, message, client_socket):
        tx_id = message.get("tx_id")
        tx = self.transactions.get(tx_id)

        if not tx or tx["state"] != "active":
            reply = {"type": "tx_error", "tx_id": tx_id, "reason": "invalid_or_not_active"}
            client_socket.sendall((json.dumps(reply) + "\n").encode("utf-8"))
            return

        op_type = message.get("op_type")
        payload = message.get("payload", {})

        # Define a resource key for locking
        if op_type == "calendar_event":
            time_str = payload.get("scheduled_time")
            if not time_str:
                reply = {
                    "type": "tx_error",
                    "tx_id": tx_id,
                    "reason": "missing_scheduled_time",
                }
                client_socket.sendall((json.dumps(reply) + "\n").encode("utf-8"))
                return

            # Uniqueness against COMMITTED events
            if self._is_time_slot_taken(time_str):
                tx["last_error"] = "time_slot_taken"
                tx["last_error_detail"] = f"Reason: Calendar time {time_str} is already booked by another user"
                tx["state"] = "aborted"
                reply = {
                    "type": "tx_aborted",
                    "tx_id": tx_id,
                    "reason": tx["last_error_detail"],
                    "scheduled_time": time_str,
                }
                client_socket.sendall((json.dumps(reply) + "\n").encode("utf-8"))
                return

            # Uniqueness inside THIS transaction (same tx adding same time twice)
            for existing_op in tx["ops"]:
                if (
                    existing_op["op_type"] == "calendar_event"
                    and existing_op["payload"].get("scheduled_time") == time_str
                ):
                    tx["last_error"] = "duplicate_calendar_event"
                    tx["last_error_detail"] = f"Reason: There is already a calendar event at {time_str} in this Transaction"
                    tx["state"] = "aborted"
                    reply = {
                        "type": "tx_aborted",
                        "tx_id": tx_id,
                        "reason": tx["last_error_detail"],
                        "scheduled_time": time_str,
                    }
                    client_socket.sendall((json.dumps(reply) + "\n").encode("utf-8"))
                    return

            resource_key = f"calendar:{time_str}"
        elif op_type == "goal_update":
            user = payload.get("user")
            goal = payload.get("goal")
            resource_key = f"goal:{user}:{goal}"
        else:
            # Unknown op
            resource_key = None

        # Simple locking: one owner per resource
        if resource_key:
            owner = self.locks.get(resource_key)
            if owner is not None and owner != tx_id:
                # Conflict -> abort this transaction
                tx["state"] = "aborted"
                reply = {
                    "type": "tx_aborted",
                    "tx_id": tx_id,
                    "reason": "lock_conflict",
                    "resource": resource_key
                }
                client_socket.sendall((json.dumps(reply) + "\n").encode("utf-8"))
                return
            else:
                self.locks[resource_key] = tx_id

        # Still active: record the operation for later commit
        tx["ops"].append({"op_type": op_type, "payload": payload})
        tx["last_activity"] = time.time()
        reply = {"type": "tx_op_ok", "tx_id": tx_id}
        client_socket.sendall((json.dumps(reply) + "\n").encode("utf-8"))

    def _handle_tx_commit(self, message, client_socket):
        tx_id = message.get("tx_id")
        tx = self.transactions.get(tx_id)
        
        if not tx or tx["state"] not in ("active", "preparing"):
            reply = {"type": "tx_error", "tx_id": tx_id, "reason": "cannot_commit"}
            client_socket.sendall((json.dumps(reply) + "\n").encode("utf-8"))
            return

        all_ops = tx["ops"]
        print(f"[{self.server_id}] Starting 2PC for TX {tx_id}")

        # --- Group ops by participant ---
        participants = {}  # Peer_addr -> [ops]
        local_ops = []

        for op in all_ops:
            peer = self._pick_participant_for_op(op)
            if peer is None:
                local_ops.append(op)
            else:
                participants.setdefault(peer, []).append(op)

        # --- Phase 1: local prepare ---
        if not self._prepare_tx_local(tx_id, local_ops):
            # Local prepare failed -> global abort
            full_reason = self._build_tx_reason(
                tx_id,
                base="2pc_local_prepare_failed",
                abort_reasons=None,
            )
            print(f"[{self.server_id}] TX {tx_id} ABORTED: {full_reason}")
            self._abort_tx_internal(tx_id, reason=full_reason, notify_client=True)
            return

        votes = []
        abort_reasons = []
        # --- Phase 1: remote prepare ---
        for peer_addr, ops in participants.items():
            msg = {"type": "tx_prepare", "tx_id": tx_id, "ops": ops}
            reply = self._send_2pc_message(peer_addr, msg, timeout=2.0)

            if not reply or reply.get("type") != "tx_vote":
                votes.append("abort")
                abort_reasons.append(f"{peer_addr} did not respond during prepare")
            else:
                vote = reply.get("vote", "abort")
                votes.append(vote)
                if vote != "commit":
                    r = reply.get("reason", "participant voted abort with no reason")
                    abort_reasons.append(f"{peer_addr} voted abort: {r}")
                    tx["last_error"] = "remote_abort"
                    tx["last_error_detail"] = r


        if any(v != "commit" for v in votes):
            # Inform participants of global abort
            for peer_addr in participants.keys():
                msg = {"type": "tx_decision", "tx_id": tx_id, "decision": "abort"}
                self._send_2pc_message(peer_addr, msg, timeout=2.0)

            # Prefer local stored detail, otherwise participant reasons, otherwise generic
            detailed = tx.get("last_error_detail") or tx.get("last_error")
            if not detailed and abort_reasons:
                detailed = "; ".join(abort_reasons)
            if not detailed:
                detailed = "2pc_global_abort"

            full_reason = detailed

            print(f"[{self.server_id}] TX {tx_id} ABORTED (global 2PC): {full_reason}")

            # Single place that notifies the client
            self._abort_tx_internal(tx_id, reason=full_reason, notify_client=True)
            return


        # --- Phase 2: global commit ---
        # Tell remote participants to commit
        for peer_addr in participants.keys():
            msg = {"type": "tx_decision", "tx_id": tx_id, "decision": "commit"}
            self._send_2pc_message(peer_addr, msg, timeout=2.0)

        # Commit locally
        self._commit_tx_local(tx_id)
        
        # Notify client
        reply = {"type": "tx_committed", "tx_id": tx_id}
        client_socket.sendall((json.dumps(reply) + "\n").encode("utf-8"))


    def _apply_calendar_tx(self, incoming_event):
        with self.lock:
            event = dict(incoming_event)
            event["id"] = len(self.calendar_events) + 1
            self.calendar_events.append(event)

        self._broadcast_tcp_message({
            "type": "calendar_update",
            "event": event,
            "all_events": self.calendar_events
        })

    def _is_time_slot_taken(self, time_str: str) -> bool:
        """Return True if scheduled_time already exists in committed events."""
        with self.lock:
            for ev in self.calendar_events:
                if ev.get("scheduled_time") == time_str:
                    return True
        return False

    def _apply_goal_tx(self, payload):
        self._broadcast_tcp_message({
            "type": "goal_update",
                "goal": payload.get("goal"),
                "user": payload.get("user"),
                "completed": payload.get("completed", False)
        })

    def _abort_tx_internal(self, tx_id, reason="client_abort", notify_client=True):
        tx = self.transactions.get(tx_id)
        if not tx or tx["state"] not in  ("active", "preparing"):
            return

        tx["state"] = "aborted"

        # Release locks held by this transaction
        to_release = [key for key, owner in list(self.locks.items()) if owner == tx_id]
        for key in to_release:
            del self.locks[key]

        if notify_client:
            client = tx["client"]
            reply = {"type": "tx_aborted", "tx_id": tx_id, "reason": reason}
            try:
                client.sendall((json.dumps(reply) + "\n").encode("utf-8"))
            except OSError:
                pass

    def _handle_tx_abort(self, message, client_socket):
        tx_id = message.get("tx_id")
        self._abort_tx_internal(tx_id, reason="client_abort", notify_client=True)

    def _handle_tx_debug(self, message, client_socket):
        """
        Send a snapshot of all transactions and current locks to the requesting client.
        Marks which transactions / locks belong to this client so they can tell
        what "other users" are holding.
        """
        # Build transaction snapshot
        tx_list = []
        for tx_id, tx_data in self.transactions.items():
            tx_list.append({
                "tx_id": tx_id,
                "state": tx_data.get("state"),
                "num_ops": len(tx_data.get("ops", [])),
                "ops": tx_data.get("ops", []),
                "is_mine": (tx_data.get("client") is client_socket),
            })

        # Build lock snapshot
        lock_list = []
        for resource_key, owner_tx_id in self.locks.items():
            owner_tx = self.transactions.get(owner_tx_id)
            owned_by_me = bool(owner_tx and owner_tx.get("client") is client_socket)
            lock_list.append({
                "resource": resource_key,
                "tx_id": owner_tx_id,
                "owned_by_me": owned_by_me,
            })

        reply = {
            "type": "tx_debug_info",
            "transactions": tx_list,
            "locks": lock_list,
        }
        try:
            client_socket.sendall((json.dumps(reply) + "\n").encode("utf-8"))
        except Exception:
            # If the client disconnected between request and response, just drop it.
            pass
    
    def _build_tx_reason(self, tx_id, base=None, abort_reasons=None):
        """
        Build a human-readable reason string for logging and client messages.

        - base: high-level label like "2pc_global_abort"
        - abort_reasons: list of strings from remote participants (tx_vote.reason)
        - tx.last_error_detail / tx.last_error: detailed local error, if any
        """
        tx = self.transactions.get(tx_id, {})
        details = tx.get("last_error_detail") or tx.get("last_error")

        parts = []
        if base:
            parts.append(base)
        if details:
            parts.append(details)
        if abort_reasons:
            parts.append("; ".join(abort_reasons))

        if not parts:
            return "unknown_transaction_error"

        return " | ".join(parts)

    def _cleanup_stale_transactions(self):
        check_interval = 5  # Seconds between sweeps
        while not self.shutdown_event.is_set():
            now = time.time()
            # Make a snapshot list to avoid modifying the dict while iterating
            for tx_id, tx in list(self.transactions.items()):
                if tx.get("state") != "active":
                    continue

                last = tx.get("last_activity", now)
                if now - last > self.tx_timeout_seconds:
                    print(f"[TX {tx_id}] Timing out after {self.tx_timeout_seconds}s of inactivity")
                    # Notify client if it’s still around
                    self._abort_tx_internal(
                        tx_id,
                        reason="timeout",
                        notify_client=True
                    )

            time.sleep(check_interval)


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

    # 2PC Helpers
    def _send_2pc_message(self, peer_addr, message, timeout=2.0):
        """Blocking, simple helper to send a JSON line to another PlatformServer and read one reply."""
        host, port = peer_addr
        try:
            with socket.create_connection((host, port), timeout=timeout) as sock:
                wire = (json.dumps(message) + "\n").encode("utf-8")
                sock.sendall(wire)

                buffer = b""
                sock.settimeout(timeout)
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk
                    if b"\n" in buffer:
                        line, _ = buffer.split(b"\n", 1)
                        if not line:
                            continue
                        reply = json.loads(line.decode("utf-8"))
                        return reply
        except Exception as e:
            print(f"[2PC] Error talking to peer {peer_addr}: {e}")
            return None

    def _prepare_tx_local(self, tx_id, ops):
        """
        Phase 1 for this server: validate + lock resources for these ops only.
        Do NOT apply calendar/goal updates yet.
        """
        tx = self.transactions.get(tx_id)
        if not tx or tx["state"] not in ("active", "preparing"):
            return False

        # Mark as preparing
        tx["state"] = "preparing"

        for op in ops:
            op_type = op["op_type"]
            payload = op["payload"]

            if op_type == "calendar_event":
                scheduled_time = payload.get("scheduled_time")
                resource_key = f"calendar:{scheduled_time}"
                if not scheduled_time:
                    tx["last_error"] = "missing_scheduled_time"
                    tx["last_error_detail"] = "calendar_event missing scheduled_time in prepare phase"
                    print(f"[{self.server_id}] PREPARE fail TX {tx_id}: missing scheduled_time")
                    return False

                # Committed uniqueness check
                if self._is_time_slot_taken(scheduled_time):
                    tx["last_error"] = "time_slot_taken"
                    tx["last_error_detail"] = (f"Reason: Calendar time {scheduled_time} is already booked by another user")
                    print(f"[{self.server_id}] PREPARE fail Transaction {tx_id}: scheduled time is already booked by another user")
                    return False

                # Uniqueness inside this transaction
                for existing_op in tx["ops"]:
                    if (existing_op["op_type"] == "calendar_event" and 
                       existing_op["payload"].get("scheduled_time") == scheduled_time):
                        tx["last_error"] = "duplicate_calendar_event"
                        tx["last_error_detail"] = (f"Reason: There is already an calendar event at {scheduled_time} in this Transaction")
                        print(f"[{self.server_id}] PREPARE fail Transaction {tx_id}: There is already an calendar event at {scheduled_time} in this Transaction")
                        return False

            elif op_type == "goal_update":
                user = payload.get("user")
                goal = payload.get("goal")
                resource_key = f"goal:{user}:{goal}"
            else:
                tx["last_error"] = "unknown_op_type"
                tx["last_error_detail"] = f"unknown op_type in prepare phase: {op_type}"
                print(f"[{self.server_id}] PREPARE fail TX {tx_id}: unknown op_type {op_type}")
                return False

            # Lock acquisition, same logic as in _handle_tx_op
            owner = self.locks.get(resource_key)
            if owner is not None and owner != tx_id:
                tx["last_error"] = "lock_conflict"
                tx["last_error_detail"] = (f"lock_conflict on {resource_key}, currently owned by TX {owner}")
                print(f"[{self.server_id}] PREPARE fail TX {tx_id}: lock_conflict on {resource_key} owned by {owner}")
                return False
            else:
                self.locks[resource_key] = tx_id

        # Store ops as "prepared" (for this server)
        tx["ops"] = ops
        tx["last_activity"] = time.time()
        return True

    def _commit_tx_local(self, tx_id):
        """
        Phase 2 local commit: apply all prepared ops and release locks.
        """
        tx = self.transactions.get(tx_id)
        if not tx or tx["state"] not in ("preparing", "prepared", "active"):
            return False

        # Actually apply
        for op in tx["ops"]:
            op_type = op["op_type"]
            payload = op["payload"]
            if op_type == "calendar_event":
                self._apply_calendar_tx(payload)
            elif op_type == "goal_update":
                self._apply_goal_tx(payload)

        # Release locks for this transaction
        resources_to_release = [res for res, owner in self.locks.items() if owner == tx_id]
        for res in resources_to_release:
            del self.locks[res]

        tx["state"] = "committed"
        tx["last_activity"] = time.time()
        return True

    def _handle_tx_prepare(self, message, client_socket):
        """
        Participant side of phase 1.
        message: { "type": "tx_prepare", "tx_id": int, "ops": [ ... ] }
        """
        tx_id = message.get("tx_id")
        ops = message.get("ops", [])

        # Ensure tx structure exists for this peer tx
        tx = self.transactions.get(tx_id)
        if tx is None:
            tx = {
                "client": None,       # remote coordinator owns this tx
                "ops": [],
                "state": "active",
                "last_activity": time.time(),
                "last_error": None,
                "last_error_detail": None,
            }
            self.transactions[tx_id] = tx 


        ok = self._prepare_tx_local(tx_id, ops)
        if ok:
            vote = "commit"
            vote_reason = None
        else:
            vote = "abort"
            vote_reason = tx.get("last_error_detail") or tx.get("last_error") or "prepare_failed"


        reply = {"type": "tx_vote", "tx_id": tx_id, "vote": vote}
        if vote_reason:
            reply["reason"] = vote_reason 
        client_socket.sendall((json.dumps(reply) + "\n").encode("utf-8"))

        # If failing, clean up immediately
        if not ok:
            self._abort_tx_internal(tx_id, reason=vote_reason, notify_client=False)

        print(f"[{self.server_id}] PREPARE for Transaction {tx_id}")

    def _handle_tx_decision(self, message, client_socket):
        """
        Participant side of phase 2.
        message: { "type": "tx_decision", "tx_id": int, "decision": "commit"|"abort" }
        """
        tx_id = message.get("tx_id")
        decision = message.get("decision")

        if decision == "commit":
            self._commit_tx_local(tx_id)
        else:
            self._abort_tx_internal(tx_id, reason="2pc_global_abort", notify_client=False)

        reply = {"type": "tx_decision_ack", "tx_id": tx_id}
        client_socket.sendall((json.dumps(reply) + "\n").encode("utf-8"))
        print(f"[{self.server_id}] DECISION {decision} for Transaction {tx_id}")

    def _pick_participant_for_op(self, op): 
        """
        Coordinator-only: returns (host, port) of the server that should own this op,
        or None if the coordinator should handle it locally.
        """
        if not self.peers or not self.is_coordinator:
            return None

        op_type = op["op_type"]
        payload = op["payload"]

        if op_type == "calendar_event":
            # Send all calendar ops to S3
            return ("localhost", 8200)
        elif op_type == "goal_update":
            # Send all goal ops to S2
            return ("localhost", 8100)

        # fallback: coordinator handles it
        return None


def node_ports_available(tcp_port: int, udp_port: int) -> bool:
    # Check TCP
    tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        tcp_sock.bind(("localhost", tcp_port))
    except OSError:
        tcp_sock.close()
        return False
    tcp_sock.close()

    # Check UDP
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        udp_sock.bind(("localhost", udp_port))
    except OSError:
        udp_sock.close()
        return False
    udp_sock.close()

    return True
                    
if __name__ == "__main__":
    if node_ports_available(8000, 8001):
        print("Launching Coordinator on 8000")
        server = PlatformServer(
            host="localhost",
            tcp_port=8000,
            udp_port=8001,
            server_id="S1",
            role="coordinator",
            peers=[("localhost", 8100), ("localhost", 8200)],
        )

    elif node_ports_available(8100, 8101):
        print("Launching Goals Node on 8100")
        server = PlatformServer(
            host="localhost",
            tcp_port=8100,
            udp_port=8101,
            server_id="S2",
            role="goals",
            peers=[("localhost", 8000)],
        )

    elif node_ports_available(8200, 8201):
        print("Launching Calendar Node on 8200")
        server = PlatformServer(
            host="localhost",
            tcp_port=8200,
            udp_port=8201,
            server_id="S3",
            role="calendar",
            peers=[("localhost", 8000)],
        )

    else:
        print("All servers are already running")
        exit()

    server.start_server()