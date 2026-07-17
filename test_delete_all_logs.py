import sys
sys.path.append('.')
from app import app
from services.db_service import get_db, run_query

with app.app_context():
    logs = run_query("SELECT id, user_id, event_description FROM logs WHERE timestamp > '2026-07-16' AND event_type = 'EXTRACT'", fetchall=True)
    for log in logs:
        if "extracted 0 posts" in log[2]:
            print(f"Deleting 0 posts log: {log}")
            run_query(f"DELETE FROM logs WHERE id = {log[0]}")
    print("Cleanup complete")
