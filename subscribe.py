"""
Global subscriber manager for Redis Pub/Sub message processing.

Implements a centralized subscriber that:
- listens to all system events
- provides logging, monitoring, notification functionality
Pub/sub from Milestone 2.

Key features:
- Subscribes to all system channels (timer, calendar, goals, platform events)
- Provides structured logging for all system events
- Implements activity monitoring with periodic statistics
- Sends notifications for important events (timer completion, goal achievements)
- Thread-safe message counting with locks
"""

import threading
import time
import json
import logging
from datetime import datetime
from pubsub import subscribe

# Configure logging for subscriber activity
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Subscribe:
    """
    Main subscriber class for processing Pub/Sub messages.
    
    Subscribes to multiple Redis channels and processes incoming messages with appropriate handlers.
    Maintains message counts and provides monitoring capabilities.
    
    Attributes:
        subscriber_id: Unique identifier for this subscriber
        running: Boolean flag controlling subscriber activity
        message_count: Dictionary tracking messages per channel
        lock: Thread lock for safe concurrent access to message counts
    """
    
    def __init__(self, subscriber_id="default_subscriber"):
        """
        Initialize the subscriber.
        
        Args:
            subscriber_id: Identifier for this subscriber instance
        """
        self.subscriber_id = subscriber_id
        self.running = True  # Control flag for graceful shutdown
        # Track message counts per channel for monitoring
        self.message_count = {
            "timer_controls": 0,    # Timer start/stop/set events
            "calendar_events": 0,   # Calendar create/update/delete events
            "goal_updates": 0,      # Goal creation and completion events
            "platform_events": 0    # General system events
        }
        self.lock = threading.Lock()  # Protect shared message counts
        
    def start_subscriptions(self):
        """
        Start subscribing to all system channels.
        
        Steps:
        1. Subscribes to all relevant Redis channels
        2. Starts a monitoring thread for activity tracking
        3. Logs subscription status
        """
        logger.info(f"Starting subscriber {self.subscriber_id}...")
        
        # Subscribe to all system channels with appropriate handlers
        subscribe("timer_controls", self._handle_timer_events)
        subscribe("calendar_events", self._handle_calendar_events)
        subscribe("goal_updates", self._handle_goal_events)
        subscribe("platform_events", self._handle_platform_events)
        subscribe("timer_updates", self._handle_timer_updates)
        
        # Log subscription details for debugging
        logger.info("Subscribed to all channels:")
        logger.info("   - timer_controls: Timer start/stop/set events")
        logger.info("   - calendar_events: Calendar CRUD operations")
        logger.info("   - goal_updates: Goal creation/completion")
        logger.info("   - platform_events: General platform events")
        logger.info("   - timer_updates: Timer tick events")
        
        # Start background thread for monitoring activity
        monitor_thread = threading.Thread(target=self._monitor_activity, daemon=True)
        monitor_thread.start()
        
    def _handle_timer_events(self, channel, message):
        """
        Handle timer control events (start, stop, set).
        
        Args:
            channel: Redis channel name ("timer_controls")
            message: Timer event data dictionary
        """
        with self.lock:
            self.message_count["timer_controls"] += 1
            
        action = message.get("action", "unknown")
        logger.info(f"Timer Event: {action.upper()} - {message.get('timestamp', '')}")
        
        # Trigger notifications for specific actions
        if action == "start":
            self._notify_timer_started(message)
        elif action == "timer_complete":
            self._notify_timer_completed()
            
    def _handle_calendar_events(self, channel, message):
        """
        Handle calendar events (create, update, delete).
        
        Args:
            channel: Redis channel name ("calendar_events")
            message: Calendar event data dictionary
        """
        with self.lock:
            self.message_count["calendar_events"] += 1
            
        event_type = message.get("type", "unknown")
        action = message.get("action", "unknown")
        
        logger.info(f"Calendar Event: {action.upper()} - {event_type}")
        
        # Extract and log event details if available
        if "event" in message:
            event_title = message["event"].get("title", "Untitled")
            logger.info(f"   Event: {event_title}")
            
        # Notify about calendar changes
        if action in ["create", "update"]:
            self._notify_calendar_change(message)
            
    def _handle_goal_events(self, channel, message):
        """
        Handle goal update events (creation, completion).
        
        Args:
            channel: Redis channel name ("goal_updates")
            message: Goal event data dictionary
        """
        with self.lock:
            self.message_count["goal_updates"] += 1
            
        goal = message.get("goal", "Unknown Goal")
        user = message.get("user", "Unknown User")
        completed = message.get("completed", False)
        
        status = "COMPLETED" if completed else "UPDATED"
        logger.info(f"Goal Event: {status} - '{goal}' by {user}")
        
        # Celebrate completed goals
        if completed:
            self._celebrate_goal_completion(goal, user)
            
    def _handle_platform_events(self, channel, message):
        """
        Handle general platform events.
        
        Args:
            channel: Redis channel name ("platform_events")
            message: Platform event data dictionary
        """
        with self.lock:
            self.message_count["platform_events"] += 1
            
        event_type = message.get("type", "unknown")
        logger.info(f"Platform Event: {event_type}")
        
    def _handle_timer_updates(self, channel, message):
        """
        Handle timer update events (ticks, state changes).
        
        Filters timer ticks to log at minute intervals, reducing log spam while still providing useful feedback.
        
        Args:
            channel: Redis channel name ("timer_updates")
            message: Timer update data dictionary
        """
        event_type = message.get("type")
        if event_type == "timer_tick":
            remaining = message.get("timer_state", {}).get("remaining_time", 0)
            # Log only at minute intervals to reduce noise
            if remaining > 0 and remaining % 60 == 0:
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                logger.info(f"Timer Update: {mins:02d}:{secs:02d} remaining")
                
    def _notify_timer_started(self, message):
        """
        Send notification for timer start events.
        
        Args:
            message: Timer start event data
        """
        duration = message.get("timer_state", {}).get("duration", 0)
        mins = duration // 60
        logger.info(f"Notification: Pomodoro timer started for {mins} minutes")
        
    def _notify_timer_completed(self):
        """
        Send notification for timer completion events.
        """
        logger.info("Notification: Pomodoro session completed! Time for a break!")
        
    def _notify_calendar_change(self, message):
        """
        Send notification for calendar changes.
        
        Args:
            message: Calendar change event data
        """
        event = message.get("event", {})
        title = event.get("title", "New Event")
        action = message.get("action", "updated")
        
        logger.info(f"Notification: Calendar event '{title}' was {action}")
        
    def _celebrate_goal_completion(self, goal, user):
        """
        Celebrate goal completion achievements.
        
        Args:
            goal: Completed goal name
            user: User who completed the goal
        """
        logger.info(f"Notification: {user} completed '{goal}'! Celebrating success!")
        
    def _monitor_activity(self):
        """
        Background thread for monitoring subscription activity.
        
        Periodically logs message counts to show system activity.
        Runs every 30 seconds while the subscriber is active.
        """
        last_count = self.message_count.copy()
        
        while self.running:
            time.sleep(30)  # Check every 30 seconds
            
            with self.lock:
                current_count = self.message_count.copy()
                
            # Calculate new messages since last check
            new_messages = {}
            for channel in current_count:
                new_messages[channel] = current_count[channel] - last_count.get(channel, 0)
                
            total_new = sum(new_messages.values())
            if total_new > 0:
                logger.info(f"Subscription Activity (last 30s): {new_messages}")
                
            last_count = current_count.copy()
            
    def get_stats(self):
        """
        Get current subscription stats.
        
        Returns:
            dict: Statistics including message counts and status
        """
        with self.lock:
            return {
                "subscriber_id": self.subscriber_id,
                "total_messages": sum(self.message_count.values()),
                "message_breakdown": self.message_count.copy(),
                "status": "active" if self.running else "inactive"
            }
            
    def stop(self):
        """
        Stop subscriber.
        
        Sets running flag to False, allowing threads to exit cleanly.
        """
        self.running = False
        logger.info(f"Subscriber {self.subscriber_id} stopped")

# Global subscriber instance for system-wide use
subscriber_manager = Subscribe()

def start_global_subscriber():
    """
    Start the global subscriber instance.
    
    Called from main.py to initialize the Pub/Sub system.
    
    Returns:
        Subscribe: The global subscriber manager instance
    """
    subscriber_manager.start_subscriptions()
    return subscriber_manager