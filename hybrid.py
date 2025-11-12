# hybrid.py
import threading
import time
import logging
from server.central_server import CentralServer
from client.p2p_client import P2PClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HybridPlatform:
    
    def __init__(self):
        self.central_server = None
        self.p2p_clients = []
        self.running = False
        
    def start_hybrid_system(self, start_clients=2):
        
        # Start the central_server
        self.central_server = CentralServer(tcp_port=9000, udp_port=9001)  # Different ports
        central_thread = threading.Thread(
            target=self.central_server.start_server,
            daemon=True,
            name="Assignment3-Server"
        )
        central_thread.start()
        time.sleep(2)
        
        # Start p2p_client
        for i in range(start_clients):
            client = P2PClient(
                client_id=f"p2p_user_{i+1}",
                server_port=9000,  # Connect to server
                p2p_port=10000 + i  # Different P2P port range
            )
            self.p2p_clients.append(client)
            time.sleep(1)
            
        self.running = True
        
        
    def stop(self):
        self.running = False
        if self.central_server:
            self.central_server._stop_server()

# Global instance
hybrid_platform = HybridPlatform()