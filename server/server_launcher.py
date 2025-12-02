"""
Server launcher for distributed deployment of the GroupSync platform.

This module provides functionality to launch multiple specialized server nodes
that work together in a distributed system. It handles port availability checking,
node role configuration, and graceful fallback to single-server mode.

Key features:
- Distributed deployment with specialized nodes (coordinator, goals, calendar)
- Automatic port availability checking
- Fallback to single-server mode when ports are occupied
- Threaded server startup for concurrent initialization
"""

import threading
import time
import socket
from .platform_server import PlatformServer

def node_ports_available(tcp_port: int, udp_port: int) -> bool:
    """
    Check if both TCP and UDP ports are available for binding.
    
    Eensures we don't try to start a server on ports that are already in use by another process.
    
    Args:
        tcp_port: TCP port number to check
        udp_port: UDP port number to check
        
    Returns:
        bool: True if both ports are available, False otherwise
        
    Implementation details:
        - Creates temporary sockets to test port availability
        - Uses OSError detection to determine if ports are occupied
        - Properly cleans up sockets even if exceptions occur
    """
    # Check TCP port availability
    tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        tcp_sock.bind(("localhost", tcp_port))
    except OSError:
        # TCP port is already in use
        tcp_sock.close()
        return False
    tcp_sock.close()

    # Check UDP port availability  
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        udp_sock.bind(("localhost", udp_port))
    except OSError:
        # UDP port is already in use
        udp_sock.close()
        return False
    udp_sock.close()

    return True  # Both ports are available

def launch_distributed_servers():
    """
    Launch distributed server nodes with specialized roles.
    
    Attempts to start three specialized servers:
    1. Coordinator (port 8000): Central coordination and transaction management
    2. Goals Node (port 8100): Specialized goal tracking operations
    3. Calendar Node (port 8200): Specialized calendar operations
    
    If ports are unavailable, falls back to single-server mode with all functionality combined.
    
    Returns:
        dict: Dictionary of launched servers keyed by server ID
        
    Architecture notes:
        - Each server runs in its own thread for concurrent operation
        - Servers are configured with peer relationships for 2PC coordination
        - Time delays between launches ensure proper initialization
    """
    servers = {}  # Track launched servers
    
    # Coordinator Node (S1)
    # The coordinator acts as the central hub for distributed transactions
    if node_ports_available(8000, 8001):
        print("Launching Coordinator on 8000")
        s1 = PlatformServer(
            host="localhost",
            tcp_port=8000,      # Main TCP port for client connections
            udp_port=8001,      # UDP port for broadcast messages
            server_id="S1",     # Unique identifier
            role="coordinator", # Central coordination role
            peers=[("localhost", 8100), ("localhost", 8200)],  # Knows about other nodes
        )
        # Start coordinator in separate thread (allows concurrent operation)
        threading.Thread(target=s1.start_server, daemon=True).start()
        servers['S1'] = s1  # Store reference to coordinator
        time.sleep(1)  # Allow coordinator to initialize before other nodes
    
    # Goals Node (S2)
    # Specialized node for goal tracking operations
    if node_ports_available(8100, 8101):
        print("Launching Goals Node on 8100")
        s2 = PlatformServer(
            host="localhost",
            tcp_port=8100,      # Dedicated TCP port for goals
            udp_port=8101,      # Dedicated UDP port
            server_id="S2",     # Goals node identifier
            role="goals",       # Specialized goal management
            peers=[("localhost", 8000)],  # Knows about coordinator
        )
        # Start goals node in separate thread
        threading.Thread(target=s2.start_server, daemon=True).start()
        servers['S2'] = s2  # Store reference to goals node
        time.sleep(1)  # Allow goals node to initialize
    
    # Calendar Node (S3)
    # Specialized node for calendar operations
    if node_ports_available(8200, 8201):
        print("Launching Calendar Node on 8200")
        s3 = PlatformServer(
            host="localhost",
            tcp_port=8200,      # Dedicated TCP port for calendar
            udp_port=8201,      # Dedicated UDP port
            server_id="S3",     # Calendar node identifier
            role="calendar",    # Specialized calendar management
            peers=[("localhost", 8000)],  # Knows about coordinator
        )
        # Start calendar node in separate thread
        threading.Thread(target=s3.start_server, daemon=True).start()
        servers['S3'] = s3  # Store reference to calendar node
        time.sleep(1)  # Allow calendar node to initialize
    
    # Fallback Mode
    # If no distributed nodes could be launched, fall back to single-server mode with all functionality combined
    if not servers:
        print("All servers are already running or ports unavailable")
        print("Launching single server on 8000")
        s1 = PlatformServer(
            host="localhost",
            tcp_port=8000,
            udp_port=8001,
            server_id="S1",
            role="coordinator"  # Combined role handles everything
        )
        threading.Thread(target=s1.start_server, daemon=True).start()
        servers['S1'] = s1
    
    # Final Initialization
    # Wait for all servers to complete initialization
    # Ensures servers are ready before clients attempt connections
    time.sleep(2)
    
    return servers  # Return dictionary of launched servers