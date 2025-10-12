import socket
import threading
import json
import time

class PlatformServer:
    
    # Init
    def __init__(self, host='localhost', tcp_port=8000, udp_port = 8001):
        self.host = host
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.connected_clients = []
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
        
        try:
            
            while True:
                
                time.sleep(1)
        
        except KeyboardInterrupt:
            print("\nKeyboard input detected.\nStopping server...")    
    
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
                
                self.connected_clients.append(client_socket)
                
                client_thread = threading.Thread(
                    target=self._handle_tcp_client,
                    args=(client_socket, address)
                )
                
                client_thread.daemon = True
                client_thread.start()
    
    # UDP Helper
    def _start_udp_server(self):
        with socket.socktt(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            
            udp_socket.bind((self.host, self.udp_port))
            
            print(f"UDP server listening on {self.host}:{self.udp_port}")
            
            while True:
                
                data, address = udp_socket.recvfrom(1024)
                message = json.loads(data.decode())
                
                self._broadcast_udp_message(message, udp_socket)

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