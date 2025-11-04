import socket
import threading
import json
import time
from datetime import datetime
import threading

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



    def connect_servers(self):
        #Attempt server connection
        try:
            print("Attempting TCP server connection...")
            self.tcp_socket.connect((self.host, self.tcp_port))
            print(f"[Client] Connected to server at {self.host}:{self.tcp_port}")

            #Start Thread
            tcp_listen_thread = threading.Thread(target=self.tcp_listener)
            tcp_listen_thread.daemon = True
            tcp_listen_thread.start()


        except Exception as e:
            print(f"[Client] Connection failed: {e}")


    def tcp_listener(self):
        #Wait and listen for message
        while self.running:
            try:
                    data = self.tcp_socket.recv(1024)
                    if not data:
                        break
                    
                    message = json.loads(data.decode())
                    self.handle_tcp_message(message)

            except Exception as e:
                print(f"[Client] TCP listener error: {e}")


    def handle_tcp_message(self, msg):
        msg_type = msg.get("type")

        if msg_type == "timer_update":
            print(f"[Server] Timer State Updated: {msg['timer_state']}")

        elif msg_type == "timer_tick":
            if not self.active_input:
                mins, secs = divmod(int(msg["remaining_time"]), 60)
                print(f"\r[Timer] Remaining: {mins:02d}:{secs:02d}   ", end="", flush=True)

        elif msg_type == "timer_complete":
            print("[Timer] Pomodoro session complete")


        else:
            print(f"[Server] Message: {msg}")

    
    #TCP message
    def send_tcp_message(self, msg):
        try:
            self.tcp_socket.send(json.dumps(msg).encode())

        except Exception as e:
            print(f"[Client] Error sending tcp message: {e}")


    #Commands
    def start_timer(self):
        # this should start a timer locally and designate this process as the master clock for it
        # each client should only have one timer running at any given time.
        # if we are already synced to another timer, call stop_timer first


        if self.timer_running:
            self.stop_timer()

        self.sync_master = None # this might end up being redundant

        # initialize timer

        # spin up a thread that runs _manage_timer
        timer_thread = threading.Thread(target=self._manage_timer())
        timer_thread.daemon = False
        timer_thread.start()



    def join_timer(self, address):
        # this should ask an existing process to join its timer
        # that process should respond either:
        #   with a confirmation of availability, and we designate them as our syncing master
        #   with the address of one of its children, which we recursively call join_timer on
        # (not every node needs to know who the master clock is)
        # start a local timer and sync it to the global one
        # if we are currently running a local timer, call stop_timer

        if self.timer_running:
            self.stop_timer()

        # ask process at address
        # handle potential non-responsiveness

        #if response == "confirmed":
        #    self.sync_master = address
        #else:
        #    self.join_timer(response)

        # spin up a thread that runs _manage_timer
        timer_thread = threading.Thread(target=self._manage_timer())
        timer_thread.daemon = False
        timer_thread.start()



    def stop_timer(self):
        # this should:
        #   if this process is the master clock, stop the timer (either designate another as master clock or
        #   tell all synced timers to stop, depends on how we want to implement it)

        #   if this process is not the master clock, end the timer management thread

        if not self.timer_running:  # if there isn't a timer running, do nothing
            return None
        elif self.sync_master is None:  # if this is the master clock
            # do behavior described above
            pass
        else:  # if we aren't the master clock and there is a timer running
            # stop local timer/end management thread
            pass



        # state cleanup
        self.children = []
        self.sync_master = None
        self.sync_grandmaster = None
        self.timer_running = False

    def reset_timer(self):
        # this should:
        #   if this process is the master clock, restart the local timer
        #   if this process is not the master clock, submit a request to our syncing master to restart its timer,
        #   which it will pass to its syncing master until it gets to the master clock

        # I'm thinking we could have an option for the master clock that determines whether
        # it will listen to that request or not
        pass

    def _request_sync(self):
        # this should ask our syncing master for an update

        # this is also where we do failure detection and handling
        #   suspect syncing master of crashing if there's not a response for a while
        #   maintain knowledge of syncing master's master (syncing grandmaster) if it exists
        #   if master is suspected, ask grandmaster for permission to take up its role
        #   grandmaster should respond either:
        #       yes, and recognize us as a new child
        #       no, and give us the identity of new syncing master
        #           this would be either the process that replaced the crashed master,
        #           or a different child (if grandmaster is still in contact with master)
        pass

    def _manage_timer(self):
        # this should be used by a thread to periodically call _request_sync and
        # to manage any child processes using us as a syncing master

        # if another process tries to join our timer, either add them as a child directly
        # or tell them to join one of our children (join_timer should be recursive)
        # this will depend on if we have the maximum number of children already (whatever we decide to set that to)


        self.timer_running = True
        while self.timer_running:
            self._request_sync()
            # check for sync requests and respond accordingly

            # check for join messages and respond accordingly
            time.sleep(1)






    def add_calendar_event(self, title, description, time_str):
        event = {
            "title": title,
            "description": description,
            "scheduled_time": time_str
        }
        self.send_tcp_message({
            "type": "calendar_event",
            "event": event
        })

    def update_goal(self, goal, user, completed=False):
        self.send_tcp_message({
            "type": "goal_update",
            "goal": goal,
            "user": user,
            "completed": completed
        })




if __name__ == "__main__":
    client = PlatformClient()
    client.connect_servers()

    #Get user input
    while True:
        #time.sleep(1)

        print("\nCommand Options (Enter number):\n"
        "1. Start Timer\n"
        "2. Stop Timer\n"
        "3. Reset Timer\n"
        "4. Join Timer\n"
        "5. Add Calendar Event\n"
        "6. Update Goal\n"
        
        "0. Exit\n")

        option = input("Select Option: ")

        if option == "1":
            client.start_timer()

        elif option == "2":
            client.stop_timer()

        elif option == "3":
            client.reset_timer()

        elif option == "4":
            address = input("Enter address: ")
            client.join_timer(address)

        elif option == "5":
            client.active_input = True
            title = input("Title: ")
            desc = input("Description: ")
            time_str = input("Time (YYYY-MM-DD HH:MM): ")
            client.add_calendar_event(title, desc, time_str)
            client.active_input = False

        elif option == "6":
            client.active_input = True
            user = input("User: ")
            goal = input("Goal: ")
            finish = input("Completed? (y/n): ").lower() == 'y'
            client.update_goal(goal, user, finish)
            client.active_input = False



        elif option == "0":
            print("Exiting...")
            client.running = False
            client.tcp_socket.close()
            break

        else:
            print("Invalid input...")


