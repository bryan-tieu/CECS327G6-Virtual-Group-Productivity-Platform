# pubsub.py
import redis
import threading
import json
import datetime

# Redis client
r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)


def publish(channel: str, message: dict):
    r.publish(channel, json.dumps(message, default=str))

def subscribe(channel: str, callback):
    pubsub = r.pubsub()
    pubsub.subscribe(channel)

    def listen():
        for msg in pubsub.listen():
            if msg['type'] == 'message':
                data = json.loads(msg['data'])
                callback(channel, data)

    thread = threading.Thread(target=listen, daemon=True)
    thread.start()
