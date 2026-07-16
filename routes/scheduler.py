from flask import Blueprint, jsonify, request
from services.db_service import run_query
from services.smart_scheduler import generate_daily_schedules, generate_schedule_for_user
from datetime import date, datetime, timedelta

scheduler_bp = Blueprint("scheduler", __name__)


@scheduler_bp.route("/schedule/today", methods=["GET"])
def get_today_schedules():
    """Get today's schedule for all active accounts."""
    today = date.today().isoformat()
    rows = run_query(
        f"SELECT ds.user_id, ds.scheduled_times, u.username, u.twitter_id, u.profile_pic, u.account_status "
        f"FROM daily_schedule ds "
        f"JOIN users u ON u.id = ds.user_id "
        f"WHERE ds.scheduled_date = '{today}'"
    )
    if not rows:
        return jsonify([]), 200

    result = []
    for row in rows:
        result.append({
            "user_id": row[0],
            "scheduled_times": row[1],
            "username": row[2],
            "twitter_id": row[3],
            "profile_pic": row[4],
            "account_status": row[5]
        })
    return jsonify(result), 200


@scheduler_bp.route("/schedule/history/<string:twitter_id>", methods=["GET"])
def get_schedule_history(twitter_id):
    """Get last 7 days of schedule + posted times for an account."""
    user_row = run_query(f"SELECT id, username FROM users WHERE twitter_id = '{twitter_id}'", fetchone=True)
    if not user_row:
        return jsonify({"error": "Account not found"}), 404

    user_id = user_row[0]
    username = user_row[1]
    cutoff = (datetime.now() - timedelta(days=7)).date().isoformat()

    # Scheduled times from daily_schedule
    schedule_rows = run_query(
        f"SELECT scheduled_date, scheduled_times FROM daily_schedule "
        f"WHERE user_id = {user_id} AND scheduled_date >= '{cutoff}' ORDER BY scheduled_date DESC"
    )

    # Actual post history (with status)
    posted_rows = run_query(
        f"SELECT tweet_text, created_at, post_status, failure_reason "
        f"FROM posted_tweets WHERE user_id = {user_id} AND created_at >= '{cutoff}' ORDER BY created_at DESC"
    )

    schedule_history = []
    if schedule_rows:
        for row in schedule_rows:
            schedule_history.append({
                "date": str(row[0]),
                "scheduled_times": row[1]
            })

    post_history = []
    if posted_rows:
        for row in posted_rows:
            post_history.append({
                "tweet_text": row[0],
                "created_at": row[1].isoformat() if row[1] else None,
                "status": row[2] or "posted",
                "failure_reason": row[3]
            })

    return jsonify({
        "twitter_id": twitter_id,
        "username": username,
        "schedule_history": schedule_history,
        "post_history": post_history
    }), 200


@scheduler_bp.route("/schedule/regenerate", methods=["POST"])
def regenerate_schedule():
    """Force regenerate today's schedule for all active accounts."""
    try:
        generate_daily_schedules()
        return jsonify({"message": "Daily schedule regenerated for all active accounts."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@scheduler_bp.route("/schedule/account/<string:twitter_id>/regenerate", methods=["POST"])
def regenerate_account_schedule(twitter_id):
    """Force regenerate today's schedule for a specific account."""
    user_row = run_query(
        f"SELECT id, posts_per_day, post_window_morning, post_window_evening, post_delay_seconds "
        f"FROM users WHERE twitter_id = '{twitter_id}'",
        fetchone=True
    )
    if not user_row:
        return jsonify({"error": "Account not found"}), 404

    user_id, posts_per_day, morning, evening, delay = user_row
    posts_per_day = int(posts_per_day) if posts_per_day else 2
    morning = morning or "6-10"
    evening = evening or "17-21"
    delay = int(delay) if delay else 1800
    today = date.today().isoformat()

    try:
        schedule_times = generate_schedule_for_user(user_id, posts_per_day, morning, evening, delay)
        run_query(f"DELETE FROM daily_schedule WHERE user_id = {user_id} AND scheduled_date = '{today}'")
        run_query(
            f"INSERT INTO daily_schedule (user_id, scheduled_date, scheduled_times) VALUES ({user_id}, '{today}', '{schedule_times}')"
        )
        return jsonify({"message": "Schedule regenerated", "scheduled_times": schedule_times}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
