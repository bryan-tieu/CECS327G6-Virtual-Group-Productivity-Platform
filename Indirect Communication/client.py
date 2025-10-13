import socket
import threading
import json
import time
from datetime import datetime

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
            print(f"[Server] Timer State Updated: {msg["timer_state"]}")

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
        self.send_tcp_message({
            "type": "timer_control",
            "action": "start"
        })

    def stop_timer(self):
        self.send_tcp_message({
            "type": "timer_control",
            "action": "stop"
        })

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

    def request_sync(self):
        self.send_tcp_message({
            "type": "request_sync"
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
        "3. Add Calendar Event\n"
        "4. Update Goal\n"
        "5. Request Sync\n"
        "0. Exit\n")

        option = input("Select Option: ")

        if option == "1":
            client.start_timer()

        elif option == "2":
            client.stop_timer()

        elif option == "3":
            client.active_input = True
            title = input("Title: ")
            desc = input("Description: ")
            time_str = input("Time (YYYY-MM-DD HH:MM): ")
            client.add_calendar_event(title, desc, time_str)
            client.active_input = False

        elif option == "4":
            client.active_input = True
            user = input("User: ")
            goal = input("Goal: ")
            finish = input("Completed? (y/n): ").lower() == 'y'
            client.update_goal(goal, user, finish)
            client.active_input = False

        elif option == "5":
            client.request_sync()

        elif option == "0":
            print("Exiting...")
            client.running = False
            client.tcp_socket.close()
            break

        else:
            print("Invalid input...")


