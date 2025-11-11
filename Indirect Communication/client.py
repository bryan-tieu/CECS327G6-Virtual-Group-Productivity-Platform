import socket
import threading
import json
import time
import math
from datetime import datetime
from queue import Queue, Empty


time_until_suspicion = 5
default_timer_length = 25.0 * 60
maximum_children = 5
tick_rate = 0.1


class PlatformClient:

    #Init
    def __init__(self, host='localhost', tcp_port=8000, udp_port = 8001):
        self.host = host
        self.tcp_port = tcp_port
        #self.udp_port = udp_port
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        #self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.running = True
        self.active_input = False
        self.timer_running = False
        self.sync_master = None
        self.sync_grandmaster = None
        self.children = []
        self.children_lock = threading.Lock()
        self.last_sync = time.time()  # log of last time a sync was received from master
        self.time_left = 0.0  # float indicating number of seconds until timer finishes
        self.inbox = Queue()  # used to pass messages from the tcp message handler to the timer management thread
        self.server_connected = False  # tracks if a connection has been made with the central server
        self.address = 'localhost'  # our own address

        # start tcp listener
        tcp_listen_thread = threading.Thread(target=self.tcp_listener)
        tcp_listen_thread.daemon = True
        tcp_listen_thread.start()

        # timer management thread
        timer_thread = threading.Thread(target=self._manage_timer)
        timer_thread.daemon = True
        timer_thread.start()

    def connect_servers(self):
        #Attempt server connection
        try:
            print("Attempting TCP server connection...")
            self.tcp_socket.connect((self.host, self.tcp_port))



        except Exception as e:
            print(f"[Client] Connection failed: {e}")

        else:
            print(f"[Client] Connected to server at {self.host}:{self.tcp_port}")
            self.server_connected = True



    def tcp_listener(self):
        #Wait and listen for message
        buffer = b""
        while True:
             if self.server_connected or self.timer_running:  # only executes if server is connected or timer is active
                try:
                        data = self.tcp_socket.recv(1024)
                        if not data:
                            break
                        buffer += data

                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            if not line:
                                continue

                            try:
                                message = json.loads(line.decode("utf-8"))
                            except Exception as e:
                                print(f"[Client] JSON parse error: {e}")
                                continue

                            self.handle_tcp_message(message)

                except Exception as e:
                    print(f"[Client] TCP listener error: {e}")




    def handle_tcp_message(self, msg):
        msg_type = msg.get("type")


        if msg_type == "timer_update":
            # save current time for syncing/failure detection
            self.last_sync = time.time()


        self.inbox.put(msg)

    
    #TCP message
    def send_tcp_message(self, msg, destination):
        try:
            wire = (json.dumps(msg) + "\n").encode("utf-8")
            # need to add addressing functionality (send message only to specified destination)
            # also prevent sending messages to anything other than children/server (except for disconnect_notice type)
            sock =

            sock.sendall(wire)
        except Exception as e:
            print(f"[Client] Error sending tcp message: {e}")


    #Commands
    def start_timer(self, duration=default_timer_length):
        if self.timer_running:
            self.stop_timer()

        self.sync_master = None  # this might end up being redundant

        # initialize timer

        self.time_left = duration
        self.timer_running = True




    def join_timer(self, address):
        # this should ask an existing process to join its timer
        # if we are currently running a local timer, call stop_timer

        if self.timer_running:
            self.stop_timer()

        # ask process at address
        msg = {"type": "join_request"}
        self.send_tcp_message(msg, address)




    def stop_timer(self):

        if self.sync_master is None and self.timer_running:  # if this is the master clock
            # designate another as master clock

            self._promotion()





        elif self.timer_running:  # if this is not the master clock
            # send a message to our parent indicating we are disconnecting
            msg = {"type": "disconnect_notice",
                    "address": self.address}
            self.send_tcp_message(msg, self.sync_master)


        # state cleanup
        self.time_left = 0.0
        self.children = []
        self.sync_master = None
        self.sync_grandmaster = None
        self.timer_running = False




    #Timer functions
    def _request_sync(self):
        # this should ask our syncing master for an update


        pass

    def _manage_timer(self):
        # this should be used by a thread to periodically call _request_sync and
        # to manage any child processes using us as a syncing master

        # if another process tries to join our timer, either add them as a child directly
        # or tell them to join one of our children (join_timer should be recursive)
        # this will depend on if we have the maximum number of children already (whatever we decide to set that to)

        crash_suspected = False


        while True:
            if self.timer_running:  # prevents thread from using resources if no timer is active
                if self.sync_master is not None:  # if we are not master clock
                    # check how long since last contact
                    if time.time() - self.last_sync > time_until_suspicion:
                        crash_suspected = True
                    self._request_sync()

                # this is also where we do failure handling
                #   if master is suspected, ask grandmaster for permission to take up its role
                #   grandmaster should respond with a update_parent, with the identity of the parent depending on
                #   whether it still has contact with the suspected process


                # check for sync requests and respond accordingly

                # check for join messages and respond accordingly
            else:  # used for joining timers
                cont = True
                while cont:
                    # retrieve message from inbox until none are left
                    try:
                        message = self.inbox.get()
                    except Empty:
                        cont = False
                        break

                    msg_type = message.get("type")
                    if msg_type == "confirm_join":
                        self.sync_master = message.get("address")
                        self.sync_grandmaster = message.get("parent_address")
                        self.server_connected = True
                        self.timer_running = True
                    elif msg_type == "deny_join":
                        self.join_timer(message.get("address"))
                    # all unrelated messages are discarded


            time.sleep(tick_rate)


    def _promotion(self):
        # sends a promotion signal to the child with the least load
        n = math.inf
        with self.children_lock:
            if self.children:  # if we have children
                for child, lineage in self.children:  # search through children and find the one with the smallest lineage
                    n = min(n, lineage)
                    if n == lineage:
                        selected = child
                self.children.remove((selected, n))


                msg = {"type": "promotion",
                       "children": self.children}
                self.send_tcp_message(msg, selected)

                msg = {"type": "update_parent",
                       "address": selected}
                for child, lineage in self.children:  # for all other children
                    self.send_tcp_message(msg, child)





    def add_calendar_event(self, title, description, time_str):
        event = {
            "title": title,
            "description": description,
            "scheduled_time": time_str
        }
        self.send_tcp_message({
            "type": "calendar_event",
            "event": event
        }, self.host)

    def update_goal(self, goal, user, completed=False):
        self.send_tcp_message({
            "type": "goal_update",
            "goal": goal,
            "user": user,
            "completed": completed
        }, self.host)




if __name__ == "__main__":
    client = PlatformClient()
    client.connect_servers()

    #Get user input
    while True:
        #time.sleep(1)

        print("\nCommand Options (Enter number):\n"
        "1. Start Timer\n"
        "2. Stop Timer\n"
        "3. Join Timer\n"
        "4. Add Calendar Event\n"
        "5. Update Goal\n"
        
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
            client.active_input = True
            title = input("Title: ")
            desc = input("Description: ")
            time_str = input("Time (YYYY-MM-DD HH:MM): ")
            client.add_calendar_event(title, desc, time_str)
            client.active_input = False

        elif option == "5":
            client.active_input = True
            user = input("User: ")
            goal = input("Goal: ")
            finish = input("Completed? (y/n): ").lower() == 'y'
            client.update_goal(goal, user, finish)
            client.active_input = False



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
            break

        else:
            print("Invalid input...")


