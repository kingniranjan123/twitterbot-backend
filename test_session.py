import requests
import json
import os
from dotenv import load_dotenv

load_dotenv("d:\\Anti-Gravity-Google\\Twitter-Facudi-v02\\backend\\.env")
rapid_key = os.getenv("RAPIDAPI_KEY")

headers = {
    "x-rapidapi-key": rapid_key,
    "x-rapidapi-host": "twttrapi.p.rapidapi.com",
    "twttr-session": "invalid_session_string"
}

url = "https://twttrapi.p.rapidapi.com/user-tweets?user_id=44196397"
res = requests.get(url, headers=headers)
print("Status:", res.status_code)
print(res.text[:200])
