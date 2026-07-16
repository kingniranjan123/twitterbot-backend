import os
import requests
import psycopg2
from dotenv import load_dotenv
import json

load_dotenv("d:\\Anti-Gravity-Google\\Twitter-Facudi-v02\\backend\\.env")
DB_URL = os.getenv("DATABASE_URL")

try:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT api_key FROM api_keys WHERE name = 'RAPIDAPI'")
    rapid_key = cur.fetchone()[0]

    cur.execute("SELECT twitter_id, session FROM users WHERE session IS NOT NULL LIMIT 1")
    user = cur.fetchone()
    twitter_id, session = user

    print(f"Testing with RapidAPI Key: {rapid_key[:5]}... User: {twitter_id}")

    endpoints = [
        f"https://twttrapi.p.rapidapi.com/user-info?username=twitter",
        f"https://twttrapi.p.rapidapi.com/user-tweets?user_id={twitter_id}"
    ]

    for url in endpoints:
        print(f"\n--- Testing Valid Session on {url} ---")
        headers = {
            "x-rapidapi-key": rapid_key,
            "x-rapidapi-host": "twttrapi.p.rapidapi.com",
            "twttr-session": session
        }
        res = requests.get(url, headers=headers)
        print("Status:", res.status_code)
        try:
            print("Response:", json.dumps(res.json(), indent=2)[:300])
        except:
            print("Response:", res.text[:300])
            
        print(f"\n--- Testing INVALID Session on {url} ---")
        headers["twttr-session"] = "invalid_session"
        res = requests.get(url, headers=headers)
        print("Status:", res.status_code)
        try:
            print("Response:", json.dumps(res.json(), indent=2)[:300])
        except:
            print("Response:", res.text[:300])

except Exception as e:
    print(f"Error: {e}")
