import sys
import os

# Add parent dir to path to import services
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.scheduler import Scheduler
from datetime import datetime

def test_generation():
    print("Testing Schedule Generation...")
    sched = Scheduler()
    schedule = sched.generate_daily_schedule()
    
    print("Generated Schedule:")
    for slot, time_val in schedule.items():
        print(f"  {slot}: {time_val}")
        
    # Validation
    assert len(schedule) == 4
    print("\n[OK] Verification passed: 4 slots generated.")

if __name__ == "__main__":
    test_generation()
