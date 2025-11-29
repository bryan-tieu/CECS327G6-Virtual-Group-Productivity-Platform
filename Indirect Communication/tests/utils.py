# tests/utils.py
import json

class FakeSocket:
    def __init__(self):
        self.sent = []

    def sendall(self, data: bytes):
        # server sends JSON + "\n"
        self.sent.append(data)

    def get_messages(self):
        messages = []
        for chunk in self.sent:
            for line in chunk.split(b"\n"):
                line = line.strip()
                if not line:
                    continue
                messages.append(json.loads(line.decode("utf-8")))
        return messages

    def last_message(self):
        msgs = self.get_messages()
        return msgs[-1] if msgs else None
