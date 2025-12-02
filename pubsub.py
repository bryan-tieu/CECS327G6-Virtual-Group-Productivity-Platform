"""
Redis Pub/Sub for indirect communication.

Provides publish/subscribe functionality for decoupled messaging across distributed system components.

Implements the indirect communication model from Milestone 2 with space and time decoupling.
"""

import redis
import threading
import json
import datetime

# Redis connection - using decode_responses for string handling
r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

def publish(channel: str, message: dict):
    """
    Publish message to Redis channel.
    
    Provides indirect communication with space and time decoupling.
    Senders don't need to know about receivers.
    
    Args:
        channel: Redis channel name
        message: Dictionary message to publish
    """
    r.publish(channel, json.dumps(message, default=str))

def subscribe(channel: str, callback):
    """
    Subscribe to Redis channel with callback.
    
    Creates a background thread that listens for messages and invokes the callback when messages arrive.
    
    Args:
        channel: Redis channel to subscribe to
        callback: Function to call with (channel, data) on message receipt
    """
    pubsub = r.pubsub()
    pubsub.subscribe(channel)

    def listen():
        """
        Background thread message listener.
        
        Continuously listens for messages and invokes callback.
        Runs in separate thread to avoid blocking.
        """
        for msg in pubsub.listen():
            if msg['type'] == 'message':
                data = json.loads(msg['data'])
                callback(channel, data)

    # Start listener in background thread (Milestone 3: Concurrency)
    thread = threading.Thread(target=listen, daemon=True)
    thread.start()