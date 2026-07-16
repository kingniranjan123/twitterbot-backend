import os
import requests
import json
from dotenv import load_dotenv

load_dotenv("d:\\Anti-Gravity-Google\\Twitter-Facudi-v02\\backend\\.env")
rapid_key = os.getenv("RAPIDAPI_KEY") or "bd48b450bemsh0d4a77b8da9f55cp1615a1jsncd3cba397edb" 
# (Note: I will fetch the key from the DB instead of assuming)
import psycopg2
try:
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cur = conn.cursor()
    cur.execute("SELECT api_key FROM api_keys WHERE name = 'RAPIDAPI'")
    rapid_key = cur.fetchone()[0]
    
    # get one valid session
    cur.execute("SELECT twitter_id, session, username FROM users WHERE session IS NOT NULL LIMIT 1")
    user = cur.fetchone()
    if not user:
        print("No valid user found")
    else:
        twitter_id, session_str, username = user
        print(f"Testing with user {username}")
        
        headers = {
            "x-rapidapi-key": rapid_key,
            "x-rapidapi-host": "twttrapi.p.rapidapi.com",
            "twttr-session": session_str
        }
        
        # Test 1: get own followers
        url = f"https://twttrapi.p.rapidapi.com/user-followers?username={username}&count=20"
        print("\nValid session:")
        res = requests.get(url, headers=headers)
        print("Status:", res.status_code)
        
        print("\nInvalid session:")
        headers["twttr-session"] = "auth_token=invalid;"
        res = requests.get(url, headers=headers)
        print("Status:", res.status_code)
        print(res.text[:200])

except Exception as e:
    print(f"Error: {e}")
