# server/server_launcher.py
import threading
import time
import socket
from .platform_server import PlatformServer

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

def launch_distributed_servers():
    """Launch S1 (coordinator), S2 (goals), S3 (calendar)"""
    servers = {}
    
    # S1 - Coordinator (port 8000)
    if node_ports_available(8000, 8001):
        print("Launching Coordinator on 8000")
        s1 = PlatformServer(
            host="localhost",
            tcp_port=8000,
            udp_port=8001,
            server_id="S1",
            role="coordinator",
            peers=[("localhost", 8100), ("localhost", 8200)],
        )
        threading.Thread(target=s1.start_server, daemon=True).start()
        servers['S1'] = s1
        time.sleep(1)
    
    # S2 - Goals (port 8100)
    if node_ports_available(8100, 8101):
        print("Launching Goals Node on 8100")
        s2 = PlatformServer(
            host="localhost",
            tcp_port=8100,
            udp_port=8101,
            server_id="S2",
            role="goals",
            peers=[("localhost", 8000)],
        )
        threading.Thread(target=s2.start_server, daemon=True).start()
        servers['S2'] = s2
        time.sleep(1)
    
    # S3 - Calendar (port 8200)
    if node_ports_available(8200, 8201):
        print("Launching Calendar Node on 8200")
        s3 = PlatformServer(
            host="localhost",
            tcp_port=8200,
            udp_port=8201,
            server_id="S3",
            role="calendar",
            peers=[("localhost", 8000)],
        )
        threading.Thread(target=s3.start_server, daemon=True).start()
        servers['S3'] = s3
        time.sleep(1)
    
    if not servers:
        print("All servers are already running or ports unavailable")
        # Fallback to single server
        print("Launching single server on 8000")
        s1 = PlatformServer(
            host="localhost",
            tcp_port=8000,
            udp_port=8001,
            server_id="S1",
            role="coordinator"
        )
        threading.Thread(target=s1.start_server, daemon=True).start()
        servers['S1'] = s1
    
    # Wait for initialization
    time.sleep(2)
    return servers