"""
Smart Scheduler Service
Generates anti-bot randomized daily posting schedules at 00:01 each day.
Supports both morning (6-10) and evening (17-21) windows.
Respects minimum delay between posts and avoids repeating times used in last 10-20 days.
"""
import random
import time
import threading
from datetime import datetime, timedelta, date
from services.db_service import run_query, log_event


def get_all_active_accounts():
    """Returns all accounts that are 'active' (not paused or held)."""
    return run_query(
        "SELECT id, twitter_id, username, posts_per_day, post_window_morning, post_window_evening, post_delay_seconds "
        "FROM users WHERE account_status = 'active' AND session IS NOT NULL"
    )


def get_recent_post_times(user_id, days=20):
    """Returns a list of (hour, minute) tuples for posts made in the last N days."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = run_query(
        f"SELECT created_at FROM posted_tweets WHERE user_id = {user_id} AND created_at >= '{cutoff}' AND post_status = 'posted'"
    )
    times = []
    if rows:
        for row in rows:
            try:
                dt = row[0] if isinstance(row[0], datetime) else datetime.fromisoformat(str(row[0]))
                times.append((dt.hour, dt.minute))
            except Exception:
                pass
    return times


def parse_window(window_str):
    """Parse '6-10' or '17-21' into (start_hour, end_hour) integers."""
    try:
        parts = str(window_str).split("-")
        return int(parts[0]), int(parts[1])
    except Exception:
        return 6, 10  # default morning


def is_too_close(new_hour, new_min, existing_times, min_gap_minutes):
    """Check if new_time is too close to any existing time."""
    new_total = new_hour * 60 + new_min
    for (h, m) in existing_times:
        existing_total = h * 60 + m
        if abs(new_total - existing_total) < min_gap_minutes:
            return True
    return False


def generate_times_in_window(start_hour, end_hour, count, existing_times, min_gap_minutes, max_attempts=200):
    """Generate `count` random times within a window that don't conflict with existing times."""
    generated = []
    for _ in range(count):
        attempts = 0
        while attempts < max_attempts:
            rand_hour = random.randint(start_hour, end_hour - 1)
            rand_min = random.randint(0, 59)
            candidate = (rand_hour, rand_min)
            all_taken = existing_times + generated
            if not is_too_close(rand_hour, rand_min, all_taken, min_gap_minutes):
                generated.append(candidate)
                break
            attempts += 1
        else:
            # Fallback: force a time even if it's a bit close
            rand_hour = random.randint(start_hour, end_hour - 1)
            rand_min = random.randint(0, 59)
            generated.append((rand_hour, rand_min))
    return generated


def decide_windows_for_today(posts_per_day, morning_window, evening_window):
    """
    Decide how many posts go in morning vs. evening.
    If posts_per_day == 1: randomly pick morning OR evening.
    If posts_per_day == 2: randomly choose BOTH morning+evening OR 2 in morning OR 2 in evening.
    If posts_per_day > 2: distribute randomly with some morning + some evening.
    """
    if posts_per_day <= 0:
        return [], []
    
    if posts_per_day == 1:
        # 50/50 pick morning or evening
        if random.random() < 0.5:
            return [morning_window], []
        else:
            return [], [evening_window]
    
    if posts_per_day == 2:
        roll = random.random()
        if roll < 0.40:
            # Both in morning
            return [morning_window, morning_window], []
        elif roll < 0.60:
            # Both in evening
            return [], [evening_window, evening_window]
        else:
            # Split morning + evening
            return [morning_window], [evening_window]
    
    # For > 2 posts: randomly distribute
    morning_count = random.randint(0, posts_per_day)
    evening_count = posts_per_day - morning_count
    return [morning_window] * morning_count, [evening_window] * evening_count


def generate_schedule_for_user(user_id, posts_per_day, morning_window_str, evening_window_str, delay_seconds):
    """
    Full schedule generation for one user.
    Returns a comma-separated string of HH:MM times.
    """
    min_gap = delay_seconds // 60  # convert seconds to minutes
    morning_window = parse_window(morning_window_str)
    evening_window = parse_window(evening_window_str)

    # Get recent post times to avoid repeating them
    recent_times = get_recent_post_times(user_id, days=random.randint(10, 20))

    morning_slots, evening_slots = decide_windows_for_today(posts_per_day, morning_window, evening_window)

    all_times = []

    # Generate morning times
    morning_count = len(morning_slots)
    if morning_count > 0:
        m_start, m_end = morning_window
        times = generate_times_in_window(m_start, m_end, morning_count, recent_times + all_times, min_gap)
        all_times.extend(times)

    # Generate evening times
    evening_count = len(evening_slots)
    if evening_count > 0:
        e_start, e_end = evening_window
        times = generate_times_in_window(e_start, e_end, evening_count, recent_times + all_times, min_gap)
        all_times.extend(times)

    # Sort times chronologically
    all_times.sort()

    # Format as "HH:MM,HH:MM"
    formatted = ",".join(f"{h:02d}:{m:02d}" for h, m in all_times)
    return formatted


def generate_daily_schedules():
    """
    Main function: generates schedules for ALL active accounts.
    Called at 00:01 daily.
    """
    print("[SmartScheduler] Generating daily schedules for all active accounts...")
    today = date.today().isoformat()
    accounts = get_all_active_accounts()

    if not accounts:
        print("[SmartScheduler] No active accounts found.")
        return

    generated_count = 0
    for acc in accounts:
        try:
            user_id = acc[0]
            twitter_id = acc[1]
            username = acc[2]
            posts_per_day = int(acc[3]) if acc[3] else 2
            morning_str = acc[4] if acc[4] else "6-10"
            evening_str = acc[5] if acc[5] else "17-21"
            delay_secs = int(acc[6]) if acc[6] else 1800

            # Check if schedule already exists
            existing = run_query(f"SELECT id FROM daily_schedule WHERE user_id = {user_id} AND scheduled_date = '{today}'")
            if existing:
                continue

            schedule_times = generate_schedule_for_user(user_id, posts_per_day, morning_str, evening_str, delay_secs)

            # Insert new schedule
            run_query(
                f"INSERT INTO daily_schedule (user_id, scheduled_date, scheduled_times) VALUES ({user_id}, '{today}', '{schedule_times}')"
            )

            log_event(user_id, "SCHEDULE_GENERATED", f"@{username} schedule for {today}: {schedule_times}")
            generated_count += 1

        except Exception as e:
            print(f"[SmartScheduler] Error generating schedule for user {acc[1]}: {e}")

    print(f"[SmartScheduler] Generated schedules for {generated_count} accounts.")


def get_due_accounts():
    """
    Returns accounts that have a scheduled post time that is NOW (within the current minute).
    Used by the post runner to determine who to post for.
    """
    now = datetime.now()
    today = now.date().isoformat()
    current_time = now.strftime("%H:%M")

    rows = run_query(
        f"SELECT ds.user_id, ds.scheduled_times, u.twitter_id, u.username "
        f"FROM daily_schedule ds "
        f"JOIN users u ON u.id = ds.user_id "
        f"WHERE ds.scheduled_date = '{today}' AND u.account_status = 'active' AND u.session IS NOT NULL"
    )
    due = []
    if rows:
        for row in rows:
            user_id = row[0]
            times_str = row[1]
            twitter_id = row[2]
            username = row[3]
            if times_str:
                times = [t.strip() for t in times_str.split(",")]
                if current_time in times:
                    due.append({"user_id": user_id, "twitter_id": twitter_id, "username": username})
    return due


def midnight_scheduler_loop():
    """
    Background loop that generates schedules at 00:01 and 12:05 every day.
    Runs in a daemon thread.
    """
    print("[SmartScheduler] Scheduler loop started.")
    while True:
        now = datetime.now()
        target_am = now.replace(hour=0, minute=1, second=0, microsecond=0)
        target_pm = now.replace(hour=12, minute=5, second=0, microsecond=0)

        if now < target_am:
            target = target_am
        elif now < target_pm:
            target = target_pm
        else:
            target = target_am + timedelta(days=1)
        
        wait_seconds = (target - now).total_seconds()
        print(f"[SmartScheduler] Next schedule generation in {int(wait_seconds)}s at {target}")
        time.sleep(wait_seconds)

        try:
            generate_daily_schedules()
        except Exception as e:
            print(f"[SmartScheduler] Error in midnight generation: {e}")


def start_midnight_scheduler():
    """Start the midnight scheduler as a background daemon thread."""
    t = threading.Thread(target=midnight_scheduler_loop, daemon=True)
    t.start()
    return t
