import socket
import threading
import json
import time
import math
from queue import Queue, Empty


time_until_suspicion = 5
default_timer_length = 25.0 * 60
maximum_children = 3
tick_rate = 0.1


class PlatformClient:

    # Init
    def __init__(self, server='localhost', server_port=8000, host='127.0.0.1', p2p_port=8001):
        self.host = host
        self.server = server
        self.server_port = server_port
        self.p2p_port = p2p_port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.running = True
        self.active_input = False
        self.timer_running = False
        self.sync_master = None
        self.sync_master_address = None
        self.sync_grandmaster = None
        self.children = []  # 2D array
        # each entry represents another client that is synced to our timer
        # format: [address, lineage, socket, last_contact]
        self.applicants = Queue()
        self.children_lock = threading.Lock()
        self.last_sync = time.time()  # log of last time a sync was received from master
        self.time_left = 0.0  # float indicating number of seconds until timer finishes
        self.inbox = Queue()  # used to pass messages from the tcp message handler to the timer management thread
        self.inbox_lock = threading.Lock()
        self.server_connected = False  # tracks if a connection has been made with the central server
        self.last_requested = None  # last time a sync was requested
        self.lamport_clock = 0

        self.current_tx_id = None

        # start tcp listener
        tcp_listen_thread = threading.Thread(target=self.tcp_listener)
        tcp_listen_thread.daemon = True
        tcp_listen_thread.start()

        # timer management thread
        timer_thread = threading.Thread(target=self._manage_timer)
        timer_thread.daemon = True
        timer_thread.start()

        # start tcp server
        tcp_thread = threading.Thread(target=self._start_p2p_server, daemon=True)
        tcp_thread.start()

    def connect_servers(self):
        # Attempt server connection
        try:
            print("Attempting TCP server connection...")
            self.server_socket.connect((self.server, self.server_port))

        except Exception as e:
            print(f"[Client] Connection failed: {e}")

        else:
            print(f"[Client] Connected to server at {self.server}:{self.server_port}")
            self.server_connected = True

    def _start_p2p_server(self):

        # TCP Socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_socket:
            tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            tcp_socket.bind((self.host, self.p2p_port))
            tcp_socket.listen(maximum_children ** 2)  # this accounts for join applicants and suspecting grandchildren
            # sockets will only be rejected if either:
            #   too many applicants ask to join at the same time
            #   all children crash simultaneously and there is at least one join applicant

            print(f"TCP server listening on {self.host}:{self.p2p_port}")

            while self.running:
                client_socket, addr = tcp_socket.accept()

                print(f"TCP Connection established with address: {addr}")

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

                    #Test (M4...)
                    if "lamport" in message:
                        self.lamport_receive(message["lamport"])
                        print(f"[Lamport={self.lamport_clock}] Updated clock from message")

                    #print(f"Message received from {address}: {message}")
                    #self.inbox.put(message)

                    #Process join messages
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
        # Wait and listen for message from central server
        buffer = b""
        while True:
            if self.server_connected:  # only executes if server is connected
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
                            #Test (M4...)
                            if "lamport" in message:
                                self.lamport_receive(message["lamport"])
                        except Exception as e:
                            print(f"[Client] JSON parse error: {e}")
                            continue
                        
                        #Test (Use for no ticks...)
                        if not self.active_input or message.get("type") != "tick":
                            self.handle_server_message(message)

                except Exception as e:
                    print(f"[Client] TCP listener error: {e}")

    def handle_server_message(self, msg):
        self.lamport_event()
        # for handling messages from central server
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
            print(f"[TX] Began transaction {self.current_tx_id}")

        elif msg_type == "tx_op_ok":
            print(f"[TX {msg['tx_id']}] Operation recorded")

        elif msg_type == "tx_committed":
            print(f"[TX {msg['tx_id']}] Commit successful")
            if self.current_tx_id == msg["tx_id"]:
                self.current_tx_id = None

        elif msg_type == "tx_aborted":
            print(f"[TX {msg['tx_id']}] Aborted: {msg.get('reason')}")
            if self.current_tx_id == msg["tx_id"]:
                self.current_tx_id = None

        elif msg_type == "tx_error":
            print(f"[TX {msg.get('tx_id')}] Error: {msg.get('reason')}")

        else:
            print(f"[Server] Message: {msg}")

    # TCP message
    def send_tcp_message(self, msg, sock):
        try:
            #Test (M4...)
            msg["lamport"] = self.lamport_send()

            wire = (json.dumps(msg) + "\n").encode("utf-8")
            # need to add addressing functionality (send message only to specified destination)
            # also prevent sending messages to anything other than children/server (except for disconnect_notice type)

            sock.sendall(wire)
            print(f"[Lamport={msg['lamport']}] Sent message {msg} to {sock}")
        except Exception as e:
            print(f"[Client] Error sending tcp message: {e}")

    # Commands
    def start_timer(self, duration=default_timer_length):
        self.lamport_event()
        if self.timer_running:
            self.stop_timer()

        self.sync_master = None  # this might end up being redundant
        self.sync_master_address = None

        # initialize timer

        self.time_left = duration
        self.timer_running = True

    def join_timer(self, address, seamless=False):
        # this should ask an existing process to join its timer
        self.lamport_event()
        # seamless joins are not visible to the user and are used to switch parents on an existing network
        if self.timer_running and not seamless:
            self.stop_timer()

        # ask process at address
        msg = {"type": "join_request",
               "address": self.host}
        self.sync_master = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if not seamless:
            print(f"Attempting to connect to {address} on port {self.p2p_port}")
        self.last_sync = time.time()
        try:
            self.sync_master.connect((address, self.p2p_port))
        except Exception as e:
            print(f"[Client] Connection failed: {e}")
            self.lamport_event()
        else:
            if not seamless:
                print(f"[Client] Connected to server at {address}:{self.p2p_port}, sending join request")
            self.send_tcp_message(msg, self.sync_master)
            self.sync_master_address = address

        self.join_reply_wait()

    #Assists join_timer...
    def join_reply_wait(self, timeout=5):
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
        if self.sync_master is None and self.timer_running:  # if this is the master clock
            # designate another as master clock
            self._promotion()

        elif self.timer_running:  # if this is not the master clock
            # send a message to our parent indicating we are disconnecting
            msg = {"type": "disconnect_notice",
                   "address": self.host}
            self.send_tcp_message(msg, self.sync_master)
            self.sync_master.close()

        # state cleanup
        self.time_left = 0.0
        with self.children_lock:
            for child in self.children:
                child[2].close()
            self.children = []
        self.sync_master = None
        self.sync_master_address = None
        self.sync_grandmaster = None
        self.timer_running = False

    # Timer functions
    def _request_sync(self):
        # this should ask our syncing master for an update
        lineage = 1
        with self.children_lock:
            for child in self.children:
                lineage += child[1]

        msg = {"type": "sync_request",
               "lineage": lineage}
        self.send_tcp_message(msg, self.sync_master)
        self.last_requested = time.time()

    def _manage_timer(self):
        # this should be used by a thread to periodically call _request_sync and
        # to manage any child processes using us as a syncing master

        # if another process tries to join our timer, either add them as a child directly
        # or tell them to join one of our children
        # this will depend on if we have the maximum number of children already (whatever we decide to set that to)

        crash_suspected = False
        last_tick = None
        response_timer = 0

        while True:
            start_time = time.time()
            if self.timer_running:  # prevents thread from using resources if no timer is active
                # update internal timer
                current = time.time()
                if last_tick is not None:  # if the timer didn't just start
                    self.time_left -= current - last_tick
                    self.lamport_event()
                    if crash_suspected:
                        response_timer += current - last_tick
                last_tick = time.time()
                if self.time_left <= 0:
                    self.lamport_event()
                    print("Timer finished")
                    self.stop_timer()

                if self.sync_master is not None:  # if we are not master clock
                    # check how long since last contact
                    if time.time() - self.last_sync > time_until_suspicion:
                        crash_suspected = True
                        self.lamport_event()
                    else:
                        self._request_sync()

                # this is also where we do failure handling
                #   if master is suspected, ask grandmaster for permission to take up its role
                #   grandmaster should respond with an update_parent, with the new parent depending on
                #   whether it still has contact with the suspected process

                if crash_suspected:
                    if response_timer > 0:  # if we're already waiting on a response from grandmaster
                        if response_timer > time_until_suspicion:  # if we now suspect grandmaster as having crashed as well
                            self.sync_grandmaster = None  # see below
                    elif self.sync_grandmaster is None:  # if the master clock goes out or grandmaster crashes, assume its responsibility to lineage
                        self.lamport_event()
                        print("Synced timer unresponsive, reverting to local timer.")
                        self.start_timer(self.time_left)
                        continue
                    else:
                        # inform master that we are disconnecting
                        msg = {"type": "disconnect_notice",
                               "address": self.host}
                        self.send_tcp_message(msg, self.sync_master)
                        self.sync_master.close()
                        self.sync_master_address = None

                        # ask grandmaster for guidance
                        temp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        try:
                            temp.connect((self.sync_grandmaster, self.p2p_port))
                        except Exception as e:
                            print(f"Synced timer became unresponsive, unable to relink with network: {e}")
                        self.send_tcp_message({"type": "suspect_crash", "address": self.host}, temp)

                # monitor children for failure, and disconnect if suspected
                with self.children_lock:
                    for child in self.children:
                        if child[3] > time_until_suspicion * 2:  # this is very lenient due to grandparents also monitoring children
                            self.lamport_event()
                            msg = {"type": "disconnect_notice",
                                   "address": self.host}
                            self.send_tcp_message(msg, child[2])
                            child[2].close()
                            self.children.remove(child)

                # check for messages and respond accordingly
                while True:
                    try:
                        message = self.inbox.get(block=False, timeout=tick_rate)
                    except Empty:
                        break

                    msg_type = message.get("type")

                    if msg_type == "sync_request":
                        requester = message.get("address")
                        with self.children_lock:
                            for child in self.children:
                                if child[0] == requester:
                                    selected = child[2]
                                    break
                        if selected is not None:
                            reply = {"type": "sync_update",
                                     "time": self.time_left,
                                     "grandparent": self.sync_grandmaster}
                            self.send_tcp_message(reply, selected)

                    elif msg_type == "sync_update":
                        self.lamport_receive(message["lamport"])
                        self.lamport_event()
                        received = time.time()
                        try:
                            self.time_left = (received - self.last_requested)/2  # uses Cristian's Method for syncing
                            self.sync_grandmaster = message.get("grandparent")
                        except TypeError:
                            print("Syncing error: Update was received without being requested")

                    elif msg_type == "join_request" or msg_type == "suspect_crash":
                        self._handle_applicants(message)

                    elif msg_type == "update_parent":
                        self.lamport_event()
                        self.join_timer(message.get("address"), seamless=True)

                    elif msg_type == "disconnect_notice":
                        sender = message.get("address")
                        if sender == self.sync_master_address:  # if our sync master disconnected, attempt to rejoin
                            self.lamport_event()
                            self.join_timer(self.sync_master_address, seamless=True)
                        else:  # check if it was one of our children
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
                        if self.sync_grandmaster is None:  # if we were one step below the master clock
                            self.sync_master = None
                            self.sync_master_address = None




            """else:  # used for joining timers
                while True:
                    # retrieve message from inbox until none are left
                    try:
                        message = self.inbox.get(block=False, timeout=tick_rate)
                        print(f"Reply: {message}")
                    except Empty:
                        # if we are attempting to join and wating on a response
                        if time.time() - self.last_sync > time_until_suspicion and self.sync_master is not None:
                            self.lamport_event()
                            print("Server took too long to respond, closing connection")
                            self.sync_master.close()
                            self.sync_master = None
                            self.sync_master_address = None
                        break

                    msg_type = message.get("type")
                    if msg_type == "confirm_join":
                        self.lamport_event()
                        self.sync_master = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        self.sync_master.connect((self.host, self.p2p_port))

                        self.sync_grandmaster = message.get("parent_address")
                        self.timer_running = True
                    elif msg_type == "deny_join":
                        self.lamport_event()
                        self.sync_master_address = None  # to ensure no garbage retention
                        self.join_timer(message.get("address"))
                    # all unrelated messages are discarded"""

            time.sleep(max(0, tick_rate - (time.time() - start_time)))

    def _promotion(self):
        # sends a promotion signal to the child with the least load
        self.lamport_event()
        n = math.inf
        with self.children_lock:
            if self.children:  # if we have children
                new_children = []  # list of children to be given to successor
                for child in self.children:  # search through children and find the one with the smallest lineage
                    new_children.append((child[0], child[1]))
                    n = min(n, child[1])
                    if n == child[1]:
                        selected = child
                        s = child[2]

                if new_children:
                    new_children.remove((selected[0], selected[1]))
                self.children.remove(selected)

                msg = {"type": "promotion"}
                self.send_tcp_message(msg, s)

                msg = {"type": "update_parent",
                       "address": selected[0]}
                for child in self.children:  # for all other children
                    self.send_tcp_message(msg, child[2])

    def _handle_applicants(self, initial):
        message_list = [initial]
        while True:  # pulls all messages out of queue
            try:
                n = self.inbox.get(block=False)
                message_list.append(n)
            except Empty:
                break

        for message in message_list:  # puts back all messages that are not relevant
            msg_type = message.get("type")
            if msg_type != "suspect_crash" and msg_type != "join_request":
                self.inbox.put(message)

        while True:  # pulls out applicants and compares their addresses to messages
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
            for child in self.children:  # ensure that suspect is actually one of our children
                if child[0] == suspect:
                    if child[3] > time_until_suspicion / 2:  # check for non-responsiveness (less lenient due to suspicion of grandchild)
                        msg = {"type": "disconnect_notice",
                               "address": self.host}
                        self.send_tcp_message(msg, child[2])
                        child[2].close()
                        self.children.remove(child)
                        action_taken = True
                        break
            if action_taken:
                msg = {"type": "update_parent",
                       "address": self.host}
            else:
                suitable_replacement = self.host  # default to ourselves, in case we have no other children
                n = math.inf
                for child in self.children:  # find child with smallest lineage
                    if child[1] < n:
                        suitable_replacement = child[0]
                        n = child[1]

                msg = {"type": "update_parent",
                       "address": suitable_replacement}
        
        self.lamport_event()
        self.send_tcp_message(msg, applicant[1])

    def _join_request(self, applicant, applicant_sock):
        if len(self.children) < maximum_children:
            parent_addr = self.sync_master_address if self.sync_master_address else self.host
            reply = {"type": "confirm_join",
                     "parent_address": parent_addr}
            with self.children_lock:
                self.children.append([applicant[0][0], 0, applicant_sock, False])
            self.lamport_event()
            #print(f"[DEBUG] Sending confirm_join to {applicant[0][0]} with parent {parent_addr}")

        else:
            reply = {"type": "deny_join",
                     "address": self.min_lineage()[0]}
            self.lamport_event()
            #print(f"[DEBUG] Sending deny_join to {applicant[0][0]}")

        self.send_tcp_message(reply, applicant_sock)

    def min_lineage(self):
        n = math.inf
        with self.children_lock:
            for child in self.children:  # find child with smallest lineage
                if child[1] < n:
                    selected = child
                    n = child[1]
        return selected

    #Lamport clock methods
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
        payload = {
            "title": title,
            "description": description,
            "scheduled_time": time_str
        }
        msg = {
            "type": "tx_op",
            "tx_id": self.current_tx_id,
            "op_type": "calendar_event",
            "payload": payload
        }
        self.send_tcp_message(msg, self.server_socket)


    def tx_update_goal(self, goal, user, completed=False):
        if self.current_tx_id is None:
            print("No active transaction. Start one first.")
            return
        payload = {
            "goal": goal,
            "user": user,
            "completed": completed
        }
        msg = {
            "type": "tx_op",
            "tx_id": self.current_tx_id,
            "op_type": "goal_update",
            "payload": payload
        }
        self.send_tcp_message(msg, self.server_socket)


if __name__ == "__main__":
    client = PlatformClient()
    client.connect_servers()

    # Get user input
    while True:
        # time.sleep(1)
        print("\nCommand Options (Enter number):\n"
        "1. Start Timer\n"
        "2. Stop Timer\n"
        "3. Join Timer\n"
        "4. Begin Transaction\n"
        
        "0. Exit\n")

        #Commment out to allow for ticks...
        client.active_input = True
        

        option = input("Select Option: ")

        if option == "1":
            client.start_timer()

        elif option == "2":
            client.stop_timer()

        elif option == "3":
            address = input("Enter address: ")
            client.join_timer(address)

            client.active_input = False

        elif option == "4":
            # Begin a new transaction
            client.begin_transaction()
            while True:
                print("\nTransaction Menu:\n"
                      "1. Add Calendar Event \n"
                      "2. Update Goal \n"
                      "3. Commit Transaction\n"
                      "4. Abort Transaction\n")
                client.active_input = True

                tx_option = input("Select an option: ")

                if tx_option == "1":
                    # Add calendar event within the current transaction
                    title = input("Title: ")
                    desc = input("Description: ")
                    time_str = input("Time (YYYY-MM-DD HH:MM): ")
                    client.active_input = False
                    client.tx_add_calendar_event(title, desc, time_str)

                elif tx_option == "2":
                    # Update goal within the current transaction
                    user = input("User: ")
                    goal = input("Goal: ")
                    finish = input("Completed? (y/n): ").strip().lower() == "y"
                    client.active_input = False
                    client.tx_update_goal(goal, user, finish)

                elif tx_option == "3":
                    # Commit and exit transaction menu
                    client.commit_transaction()
                    client.active_input = False
                    break

                elif tx_option == "4":
                    # Abort and exit transaction menu
                    client.abort_transaction()
                    client.active_input = False
                    break
                
                else:
                    print("Invalid input...")

        elif option == "0":
            print("Exiting...")
            client.running = False
            try:
                client.stop_event.set()
            except:
                pass
            
            try: 
                client.tcp_socket.close()
            except:
                pass

            try:
                client.stop_timer()
            except:
                pass
            break

        else:
            print("Invalid input...")
