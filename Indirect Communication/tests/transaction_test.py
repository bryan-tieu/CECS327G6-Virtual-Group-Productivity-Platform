# tests/test_transaction.py
from tests.utils import FakeSocket
from datetime import datetime
import threading
import time

def test_happy_calendar_transaction(server):
  """
  This test demonstrate a happy calendar event transaction
  """
  sock = FakeSocket()

  # Begin transaction
  server._handle_tx_begin({"type": "tx_begin"}, sock)
  msg = sock.last_message()
  assert msg["type"] == "tx_started"
  tx_id = msg["tx_id"]

  # Add calendar event
  time_str = "2025-12-01 10:00"
  op_msg = {
    "type": "tx_op",
    "tx_id": tx_id,
    "op_type": "calendar_event",
    "payload": {"title": "Meeting", "description": "Discuss stuff", "scheduled_time": time_str},
  }
  sock.sent.clear()
  server._handle_tx_op(op_msg, sock)
  msg = sock.last_message()
  assert msg["type"] == "tx_op_ok"
  assert msg["tx_id"] == tx_id

  # Commit
  sock.sent.clear()
  server._handle_tx_commit({"type": "tx_commit", "tx_id": tx_id}, sock)
  msg = sock.last_message()
  assert msg["type"] == "tx_committed"
  assert msg["tx_id"] == tx_id

  # Server state checks
  assert len(server.calendar_events) == 1
  event = server.calendar_events[0]
  assert event["scheduled_time"] == time_str
  assert server.transactions[tx_id]["state"] == "committed"
  assert not any(owner == tx_id for owner in server.locks.values())

def test_double_booking_conflict(server):
  """
  This test demonstrate when a client try to book an event with a date & time that conflicts
  the date & time with an existing event. The result is the client will fail to book due to conflicting scheduled time
  """
  time_str = "2025-12-01 10:00"

  # First client / tx -> successful booking
  sock1 = FakeSocket()
  server._handle_tx_begin({"type": "tx_begin"}, sock1)
  tx1 = sock1.last_message()["tx_id"]

  op1 = {
    "type": "tx_op",
    "tx_id": tx1,
    "op_type": "calendar_event",
    "payload": {"title": "First", "description": "First booking", "scheduled_time": time_str},
  }
  server._handle_tx_op(op1, sock1)
  server._handle_tx_commit({"type": "tx_commit", "tx_id": tx1}, sock1)
  assert server.transactions[tx1]["state"] == "committed"

  # Second client / tx -> should be aborted because slot is taken
  sock2 = FakeSocket()
  server._handle_tx_begin({"type": "tx_begin"}, sock2)
  tx2 = sock2.last_message()["tx_id"]

  op2 = {
    "type": "tx_op",
    "tx_id": tx2,
    "op_type": "calendar_event",
    "payload": {"title": "Second", "description": "Try same time", "scheduled_time": time_str},
  }
  sock2.sent.clear()
  server._handle_tx_op(op2, sock2)
  msg = sock2.last_message()
  assert msg["type"] == "tx_aborted"
  assert msg["reason"] == ("this time slot is already taken")
  assert server.transactions[tx2]["state"] == "aborted"

def test_lock_conflict_between_active_transactions(server):
  """ 
  This test demonstrate when 2 clients with 2 active transaction try to book calendar events that
  happen at the same date & time. The result is which ever client adds the event first to the transaction,
  that client gets to keep it while the other one will be aborted.
  """
  time_str = "2025-12-02 12:00"

  # Firt client acquires lock on time slot
  s1 = FakeSocket()
  server._handle_tx_begin({"type": "tx_begin"}, s1)
  tx1 = s1.last_message()["tx_id"]

  op1 = {
    "type": "tx_op",
    "tx_id": tx1,
    "op_type": "calendar_event",
    "payload": {"title": "Owner", "description": "First to lock", "scheduled_time": time_str},
  }
  server._handle_tx_op(op1, s1)
  assert server.locks[f"calendar:{time_str}"] == tx1

  # Second client attempts to use the same resource -> lock conflict
  s2 = FakeSocket()
  server._handle_tx_begin({"type": "tx_begin"}, s2)
  tx2 = s2.last_message()["tx_id"]

  op2 = {
    "type": "tx_op",
    "tx_id": tx2,
    "op_type": "calendar_event",
    "payload": { "title": "2nd Attempt", "description": "Should Conflict", "scheduled_time": time_str},
  }
  s2.sent.clear()
  server._handle_tx_op(op2, s2)
  msg = s2.last_message()
  assert msg["type"] == "tx_aborted"
  assert msg["reason"] == "lock_conflict"
  assert msg["resource"] == f"calendar:{time_str}"
  assert server.transactions[tx2]["state"] == "aborted"



def test_transaction_timeout_cleanup(server):
  """
  This test demonstrates when a client begins a transaction and never finished it (idle).
  The result is the transaction will be aborted after a set amount of time.
  """
  server.tx_timeout_seconds = 0.1  # Very short for test

  sock = FakeSocket()
  server._handle_tx_begin({"type": "tx_begin"}, sock)
  tx_id = sock.last_message()["tx_id"]

  # Record op, then go idle
  op = {
    "type": "tx_op",
    "tx_id": tx_id,
    "op_type": "goal_update",
    "payload": {"user": "alice", "goal": "run", "completed": False},
  }
  server._handle_tx_op(op, sock)

  # Run cleanup in a small background thread just once
  def run_once():
    # Simulate one pass of the loop
    now = time.time()
    for tid, tx in list(server.transactions.items()):
      if tx.get("state") != "active":
          continue
      last = tx.get("last_activity", now)
      if now - last > server.tx_timeout_seconds:
          server._abort_tx_internal(tid, reason="timeout", notify_client=True)

  time.sleep(0.2)  # Wait enough for timeout
  run_once()

  assert server.transactions[tx_id]["state"] == "aborted"

def test_duplicate_time_in_same_transaction_aborts(server):
  """
  This test will demonstrate when a client try adding 2 calendar events that take place
  at the same date & time in the same transaction. The first event will be added successfully
  and the second event will abort due to lock conflict
  """
  sock = FakeSocket()
  server._handle_tx_begin({"type": "tx_begin"}, sock)
  tx_id = sock.last_message()["tx_id"]

  time_str = "2025-12-02 09:00"
  op = {
      "type": "tx_op",
      "tx_id": tx_id,
      "op_type": "calendar_event",
      "payload": {"title": "One", "description": "", "scheduled_time": time_str},
  }
  # First add OK
  server._handle_tx_op(op, sock)

  sock.sent.clear()
  # Second add same time -> should abort
  server._handle_tx_op(op, sock)
  msg = sock.last_message()

  assert msg["type"] == "tx_aborted"
  assert server.transactions[tx_id]["state"] == "aborted"
  # Commit must fail
  sock.sent.clear()
  server._handle_tx_commit({"type": "tx_commit", "tx_id": tx_id}, sock)
  # Still no committed events for that tx

def test_explicit_abort_releases_locks_and_prevents_commit(server):
  """
  This test demonstrate when a client begin a transaction, add an event, then abort the transaction
  """
  sock = FakeSocket()
  server._handle_tx_begin({"type": "tx_begin"}, sock)
  tx_id = sock.last_message()["tx_id"]

  time_str = "2025-12-04 12:00"
  op = {
      "type": "tx_op",
      "tx_id": tx_id,
      "op_type": "calendar_event",
      "payload": {"title": "Meet", "description": "", "scheduled_time": time_str},
  }
  server._handle_tx_op(op, sock)

  # Lock held
  assert server.locks[f"calendar:{time_str}"] == tx_id

  sock.sent.clear()
  server._handle_tx_abort({"type": "tx_abort", "tx_id": tx_id}, sock)
  assert server.transactions[tx_id]["state"] == "aborted"
  assert f"calendar:{time_str}" not in server.locks

  # Commit after abort should fail with tx_error even though this part is not exposed to the client
  sock.sent.clear()
  server._handle_tx_commit({"type": "tx_commit", "tx_id": tx_id}, sock)
  msg = sock.last_message()
  assert msg["type"] == "tx_error"
  assert msg["reason"] == "cannot_commit"

def test_transaction_op_with_invalid_transaction_id_returns_error(server):
  """
  This test demonstrates adding an event with an invalid transaction ID which will results in an error
  """
  sock = FakeSocket()
  invalid_tx_id = 999  # no such transaction ID

  op = {
      "type": "tx_op",
      "tx_id": invalid_tx_id,
      "op_type": "calendar_event",
      "payload": {"title": "What is this transaction ID", "description": "It's bs", "scheduled_time": "2025-12-05 10:00"},
  }

  server._handle_tx_op(op, sock)
  msg = sock.last_message()

  assert msg["type"] == "tx_error"
  assert msg["tx_id"] == invalid_tx_id
  assert msg["reason"] == "invalid_or_not_active"

def test_transaction_commit_with_invalid_transaction_id_returns_error(server):
  """
  This test demonstrates committing an event with an invalid transaction ID which will results in an error
  """
  sock = FakeSocket()
  invalid_tx_id = 999

  server._handle_tx_commit({"type": "tx_commit", "tx_id": invalid_tx_id}, sock)
  msg = sock.last_message()

  assert msg["type"] == "tx_error"
  assert msg["tx_id"] == invalid_tx_id
  assert msg["reason"] == "cannot_commit"

def test_calendar_op_missing_scheduled_time_returns_error(server):
  sock = FakeSocket()
  server._handle_tx_begin({"type": "tx_begin"}, sock)
  tx_id = sock.last_message()["tx_id"]

  op = {
    "type": "tx_op",
    "tx_id": tx_id,
    "op_type": "calendar_event",
    "payload": {"title": "No time", "description": "oops"},  # No scheduled_time
  }

  server._handle_tx_op(op, sock)
  msg = sock.last_message()

  assert msg["type"] == "tx_error"
  assert msg["reason"] == "missing_scheduled_time"
  # Transaction should still be active and no locks created
  assert server.transactions[tx_id]["state"] == "active"
  assert len(server.locks) == 0
  assert server.transactions[tx_id]["ops"] == []

def test_goal_update_transaction_commit(server):
  """
  This test demonstrate a happy goal update transaction
  """
  broadcasts = []
  original = server._broadcast_tcp_message
  server._broadcast_tcp_message = lambda msg: broadcasts.append(msg)

  try:
    sock = FakeSocket()
    server._handle_tx_begin({"type": "tx_begin"}, sock)
    tx_id = sock.last_message()["tx_id"]

    op = {
      "type": "tx_op",
      "tx_id": tx_id,
      "op_type": "goal_update",
      "payload": {"user": "Tin", "goal": "run", "completed": True},
    }
    server._handle_tx_op(op, sock)
    msg = sock.last_message()
    assert msg["type"] == "tx_op_ok"

    server._handle_tx_commit({"type": "tx_commit", "tx_id": tx_id}, sock)
    msg = sock.last_message()
    assert msg["type"] == "tx_committed"
    assert server.transactions[tx_id]["state"] == "committed"

    # Verify one goal_update broadcast
    assert len(broadcasts) == 1
    assert broadcasts[0]["type"] == "goal_update"
    assert broadcasts[0]["user"] == "Tin"
    assert broadcasts[0]["goal"] == "run"
    assert broadcasts[0]["completed"] is True
  finally:
    server._broadcast_tcp_message = original

def test_goal_update_lock_conflict_during_active_transactions(server):
  """
  This test demonstrate lock conflict between 2 clients trying to update the same goal at the same time
  """
  s1 = FakeSocket()
  server._handle_tx_begin({"type": "tx_begin"}, s1)
  tx1 = s1.last_message()["tx_id"]

  op1 = {
    "type": "tx_op",
    "tx_id": tx1,
    "op_type": "goal_update",
    "payload": {"user": "Tin", "goal": "run", "completed": False},
  }
  server._handle_tx_op(op1, s1)
  assert server.locks["goal:Tin:run"] == tx1

  # Second transaction: same (user, goal) -> lock_conflict
  s2 = FakeSocket()
  server._handle_tx_begin({"type": "tx_begin"}, s2)
  tx2 = s2.last_message()["tx_id"]

  op2 = {
    "type": "tx_op",
    "tx_id": tx2,
    "op_type": "goal_update",
    "payload": {"user": "Tin", "goal": "run", "completed": True},
  }
  s2.sent.clear()
  server._handle_tx_op(op2, s2)
  msg = s2.last_message()

  assert msg["type"] == "tx_aborted"
  assert msg["reason"] == "lock_conflict"
  assert msg["resource"] == "goal:Tin:run"
  assert server.transactions[tx2]["state"] == "aborted"

def test_goal_update_succeeds_after_first_commit(server):
  """
  This test demonstrates that after the client commits a goal update
  (and releases the lock), another/same client can successfully update
  the same goal without a lock conflict.
  """
  s1 = FakeSocket()
  server._handle_tx_begin({"type": "tx_begin"}, s1)
  tx1 = s1.last_message()["tx_id"]

  op1 = {
    "type": "tx_op",
    "tx_id": tx1,
    "op_type": "goal_update",
    "payload": {"user": "Tin", "goal": "run", "completed": False},
  }
  server._handle_tx_op(op1, s1)
  msg1 = s1.last_message()
  assert msg1["type"] == "tx_op_ok"
  assert server.locks["goal:Tin:run"] == tx1  # Lock is held by tx1

  # Commit first transaction -> should release lock
  s1.sent.clear()
  server._handle_tx_commit({"type": "tx_commit", "tx_id": tx1}, s1)
  msg_commit = s1.last_message()
  assert msg_commit["type"] == "tx_committed"
  assert server.transactions[tx1]["state"] == "committed"
  assert "goal:Tin:run" not in server.locks  # lock released

  # Second transaction: same (user, goal) -> lock_conflict
  s2 = FakeSocket()
  server._handle_tx_begin({"type": "tx_begin"}, s2)
  tx2 = s2.last_message()["tx_id"]

  op2 = {
    "type": "tx_op",
    "tx_id": tx2,
    "op_type": "goal_update",
    "payload": {"user": "Tin", "goal": "run", "completed": True},
  }
  s2.sent.clear()
  server._handle_tx_op(op2, s2)
  msg2 = s2.last_message()
  assert msg2["type"] == "tx_op_ok"
  assert server.locks["goal:Tin:run"] == tx2

  s2.sent.clear()
  server._handle_tx_commit({"type": "tx_commit", "tx_id": tx2}, s2)
  msg_commit2 = s2.last_message()
  assert msg_commit2["type"] == "tx_committed"
  assert server.transactions[tx2]["state"] == "committed"
  assert "goal:Tin:run" not in server.locks  # lock released

def test_multiple_ops_in_a_transaction(server):
  """
  This test demonstrates atomicity for a transaction that contains
  multiple operations of different types: a calendar_event and a goal_update.
  Both operations should be applied on commit, and all locks released.
  """
  broadcasts = []
  original_broadcast = server._broadcast_tcp_message
  def fake_broadcast(msg):
    broadcasts.append(msg)
  server._broadcast_tcp_message = fake_broadcast

  try: 
    sock = FakeSocket()
    server._handle_tx_begin({"type": "tx_begin"}, sock)
    tx_id = sock.last_message()["tx_id"]
    
    op1 = {
      "type": "tx_op",
      "tx_id": tx_id,
      "op_type": "calendar_event",
      "payload": {"title": "First", "description": "First booking", "scheduled_time": "2025-12-05 10:00"},
    }
    sock.sent.clear()
    server._handle_tx_op(op1, sock)
    msg = sock.last_message()
    assert msg["type"] == "tx_op_ok"
    assert msg["tx_id"] == tx_id

    op2 = {
      "type": "tx_op",
      "tx_id": tx_id,
      "op_type": "goal_update",
      "payload": {"user": "Tin", "goal": "run", "completed": True},
    }

    sock.sent.clear()
    server._handle_tx_op(op2, sock)
    msg = sock.last_message()
    assert msg["type"] == "tx_op_ok"
    assert msg["tx_id"] == tx_id

    # At this point, both calendar and goal locks should be held by this transaction
    assert server.locks["calendar:2025-12-05 10:00"] == tx_id
    assert server.locks["goal:Tin:run"] == tx_id

    # Commit the transaction
    sock.sent.clear()
    server._handle_tx_commit({"type": "tx_commit", "tx_id": tx_id}, sock)
    msg = sock.last_message()
    assert msg["type"] == "tx_committed"
    assert msg["tx_id"] == tx_id
    assert server.transactions[tx_id]["state"] == "committed"

    # All locks held by this tx should be released
    assert "calendar:2025-12-05 10:00" not in server.locks
    assert "goal:Tin:run" not in server.locks
    assert not any(owner == tx_id for owner in server.locks.values())

    # Check if there are 2 broadcasts 
    assert len(broadcasts) == 2

  finally:
    # Restore original broadcast method so other tests are unaffected
    server._broadcast_tcp_message = original_broadcast
