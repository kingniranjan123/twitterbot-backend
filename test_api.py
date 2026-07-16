import requests
import json

try:
    # Test Railway backend
    res = requests.get('https://twitterbot-backend-production.up.railway.app/api/accounts')
    print("Status:", res.status_code)
    print("Data:", json.dumps(res.json(), indent=2)[:500])
except Exception as e:
    print("Error:", e)
