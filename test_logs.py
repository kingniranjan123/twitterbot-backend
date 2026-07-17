import sys
sys.path.append('.')
from app import app
from services.db_service import get_db, run_query

with app.app_context():
    user = run_query("SELECT id FROM users WHERE username = 'Actress_OnFire'", fetchone=True)
    if user:
        print(run_query(f"SELECT * FROM logs WHERE user_id = '{user[0]}' ORDER BY timestamp DESC LIMIT 5", fetchall=True))
