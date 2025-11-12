# subscribe.py
import threading
import time
import json
import logging
from datetime import datetime
from pubsub import subscribe

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Subscribe:
    """
    Demonstrates indirect communication via Redis pub/sub
    Listens to all platform events and reacts accordingly
    """
    
    def __init__(self, subscriber_id="default_subscriber"):
        self.subscriber_id = subscriber_id
        self.running = True
        self.message_count = {
            "timer_controls": 0,
            "calendar_events": 0,
            "goal_updates": 0,
            "platform_events": 0
        }
        self.lock = threading.Lock()
        
    def start_subscriptions(self):
        # Subscribe to all relevant channels
        logger.info(f"Starting subscriber {self.subscriber_id}...")
        
        # Subscribe to all event channels
        subscribe("timer_controls", self._handle_timer_events)
        subscribe("calendar_events", self._handle_calendar_events)
        subscribe("goal_updates", self._handle_goal_events)
        subscribe("platform_events", self._handle_platform_events)
        subscribe("timer_updates", self._handle_timer_updates)
        
        logger.info("Subscribed to all channels:")
        logger.info("   - timer_controls: Timer start/stop/set events")
        logger.info("   - calendar_events: Calendar CRUD operations")
        logger.info("   - goal_updates: Goal creation/completion")
        logger.info("   - platform_events: General platform events")
        logger.info("   - timer_updates: Timer tick events")
        
        # Start monitoring thread
        monitor_thread = threading.Thread(target=self._monitor_activity, daemon=True)
        monitor_thread.start()
        
    def _handle_timer_events(self, channel, message):
        # Handle timer control events
        with self.lock:
            self.message_count["timer_controls"] += 1
            
        action = message.get("action", "unknown")
        logger.info(f"Timer Event: {action.upper()} - {message.get('timestamp', '')}")
        
        # React to specific timer events
        if action == "start":
            self._notify_timer_started(message)
        elif action == "timer_complete":
            self._notify_timer_completed()
            
    def _handle_calendar_events(self, channel, message):
        # Handle calendar events
        with self.lock:
            self.message_count["calendar_events"] += 1
            
        event_type = message.get("type", "unknown")
        action = message.get("action", "unknown")
        
        logger.info(f"Calendar Event: {action.upper()} - {event_type}")
        
        if "event" in message:
            event_title = message["event"].get("title", "Untitled")
            logger.info(f"   Event: {event_title}")
            
        # React to calendar updates
        if action in ["create", "update"]:
            self._notify_calendar_change(message)
            
    def _handle_goal_events(self, channel, message):
        # Handle goal updates
        with self.lock:
            self.message_count["goal_updates"] += 1
            
        goal = message.get("goal", "Unknown Goal")
        user = message.get("user", "Unknown User")
        completed = message.get("completed", False)
        
        status = "COMPLETED" if completed else "UPDATED"
        logger.info(f"Goal Event: {status} - '{goal}' by {user}")
        
        # React to goal completion
        if completed:
            self._celebrate_goal_completion(goal, user)
            
    def _handle_platform_events(self, channel, message):
        # Handle general platform events
        with self.lock:
            self.message_count["platform_events"] += 1
            
        event_type = message.get("type", "unknown")
        logger.info(f"Platform Event: {event_type}")
        
    def _handle_timer_updates(self, channel, message):
        # Handle timer tick events (for demonstration)
        event_type = message.get("type")
        if event_type == "timer_tick":
            remaining = message.get("timer_state", {}).get("remaining_time", 0)
            if remaining > 0 and remaining % 60 == 0:  # Log every minute
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                logger.info(f"⏱Timer Update: {mins:02d}:{secs:02d} remaining")
                
    def _notify_timer_started(self, message):
        # React to timer start events
        duration = message.get("timer_state", {}).get("duration", 0)
        mins = duration // 60
        logger.info(f"Notification: Pomodoro timer started for {mins} minutes")
        
    def _notify_timer_completed(self):
        # React to timer completion
        logger.info("Notification: Pomodoro session completed! Time for a break!")
        
    def _notify_calendar_change(self, message):
        # React to calendar changes
        event = message.get("event", {})
        title = event.get("title", "New Event")
        action = message.get("action", "updated")
        
        logger.info(f"Notification: Calendar event '{title}' was {action}")
        
    def _celebrate_goal_completion(self, goal, user):
        # React to goal completion
        logger.info(f"Notification: {user} completed '{goal}'! Celebrating success!")
        
    def _monitor_activity(self):
        # Monitor and report subscription activity
        last_count = self.message_count.copy()
        
        while self.running:
            time.sleep(30)  # Report every 30 seconds
            
            with self.lock:
                current_count = self.message_count.copy()
                
            # Calculate new messages since last report
            new_messages = {}
            for channel in current_count:
                new_messages[channel] = current_count[channel] - last_count.get(channel, 0)
                
            total_new = sum(new_messages.values())
            if total_new > 0:
                logger.info(f"Subscription Activity (last 30s): {new_messages}")
                
            last_count = current_count.copy()
            
    def get_stats(self):
        # Get subscription statistics
        with self.lock:
            return {
                "subscriber_id": self.subscriber_id,
                "total_messages": sum(self.message_count.values()),
                "message_breakdown": self.message_count.copy(),
                "status": "active" if self.running else "inactive"
            }
            
    def stop(self):
        # Stop the subscriber
        self.running = False
        logger.info(f"Subscriber {self.subscriber_id} stopped")

# Global subscriber instance
subscriber_manager = Subscribe()

def start_global_subscriber():
    subscriber_manager.start_subscriptions()
    return subscriber_manager
