# pubsub.py
import redis
import threading
import json

# Redis client
try:
    r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    r.ping()
except redis.ConnectionError:
    print("Redis connection error")
    r = None

def publish(channel: str, message: dict):
    """Publish a message to a Redis channel"""
    r.publish(channel, json.dumps(message))

def subscribe(channel: str, callback):
    """Subscribe to a Redis channel and call callback(channel, message) for each message"""
    pubsub = r.pubsub()
    pubsub.subscribe(channel)

    def listen():
        for msg in pubsub.listen():
            if msg['type'] == 'message':
                data = json.loads(msg['data'])
                callback(channel, data)

    thread = threading.Thread(target=listen, daemon=True)
    thread.start()
