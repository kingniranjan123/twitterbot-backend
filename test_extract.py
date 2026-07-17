import sys
import asyncio
import threading
sys.path.append('.')
from app import app
from services.db_service import get_db, run_query
from services.fetch_tweets import fetch_tweets_for_single_user

with app.app_context():
    user = run_query("SELECT id FROM users WHERE username = 'Actress_OnFire'", fetchone=True)
    if user:
        event = threading.Event()
        asyncio.run(fetch_tweets_for_single_user(user[0], event))
