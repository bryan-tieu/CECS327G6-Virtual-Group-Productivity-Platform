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



    def connect_servers(self):
        #Attempt server connection
        try:
            print("Attempting TCP server connection...")
            self.tcp_socket.connect((self.host, self.tcp_port))
            print(f"[Client] Connected to server at {self.host}:{self.tcp_port}")


        except Exception as e:
            print(f"[Client] Connection failed: {e}")



if __name__ == "__main__":
    client = PlatformClient()
    client.connect_servers()

