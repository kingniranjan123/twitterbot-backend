import random
import time
from datetime import datetime, timedelta
import threading

class Scheduler:
    def __init__(self):
        self.daily_slots = [
            (0, 6),
            (6, 12),
            (12, 18),
            (18, 24)
        ]
        self.current_schedule = {}
        self.lock = threading.Lock()

    def generate_daily_schedule(self):
        """
        Generates a new schedule for the current day (or next 24h).
        Each slot gets a random start time.
        """
        now = datetime.now()
        schedule = {}
        
        for start_hour, end_hour in self.daily_slots:
            # Random minute and second
            rand_hour = random.randint(start_hour, end_hour - 1)
            rand_minute = random.randint(0, 59)
            rand_second = random.randint(0, 59)
            
            # Create the target time for today
            target_time = now.replace(hour=rand_hour, minute=rand_minute, second=rand_second, microsecond=0)
            
            # If the generated time has already passed today, we might schedule it for tomorrow
            # OR just accept it's passed (depending on logic). For now, we generate for "today".
            # If logic runs continously, we just check if we hit the time.
            
            slot_key = f"{start_hour:02d}-{end_hour:02d}"
            schedule[slot_key] = target_time
            
        with self.lock:
            self.current_schedule = schedule
            
        return schedule

    def get_next_run_time(self):
        """
        Returns the next scheduled run time from the current schedule.
        """
        now = datetime.now()
        with self.lock:
            # Sort times
            future_runs = [t for t in self.current_schedule.values() if t > now]
            if not future_runs:
                # If no runs left today, maybe generate for tomorrow? 
                # For simplicity, let's say we regenerate if empty or all passed.
                return None
            return min(future_runs)

    def should_run_now(self, slot_key):
        """
        Checks if the specific slot is due to run. 
        Note: This is a bit simplistic. Better to just check "is there any slot due?".
        """
        pass

    def get_schedule_display(self):
        with self.lock:
            return {k: v.strftime("%Y-%m-%d %H:%M:%S") for k, v in self.current_schedule.items()}

# Global instance
scheduler = Scheduler()
