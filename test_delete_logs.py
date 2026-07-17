import sys
sys.path.append('.')
from app import app
from services.db_service import get_db, run_query

with app.app_context():
    print(run_query("DELETE FROM logs WHERE user_id = 40 AND timestamp > '2026-07-16' AND event_type = 'EXTRACT'"))
    print("Deleted successfully")
