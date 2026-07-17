import sys
sys.path.append('.')
from app import app
from services.db_service import get_db, run_query

with app.app_context():
    logs = run_query("SELECT user_id, event_type, event_description, timestamp FROM logs ORDER BY id DESC LIMIT 15", fetchall=True)
    for log in logs:
        print(log)
