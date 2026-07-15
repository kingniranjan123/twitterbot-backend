import requests
import json
import time

BASE_URL = "http://127.0.0.1:5000"

# Note: Adjust twitter_id and user_id to existing ones in DB for better testing if needed
TEST_USER_ID = "2"
TEST_TWITTER_ID = "1537243954" # Just a placeholder, you can get a real one from /api/accounts

endpoints = [
    {"category": "System", "route": "/", "method": "GET", "desc": "API Health check & Welcome message"},
    {"category": "System (Scheduler)", "route": "/start-fetch", "method": "POST", "desc": "Start dynamic scheduler"},
    {"category": "System (Scheduler)", "route": "/status-fetch", "method": "GET", "desc": "Status dynamic scheduler"},
    {"category": "System (Scheduler)", "route": "/stop-fetch", "method": "POST", "desc": "Stop dynamic scheduler"},
    {"category": "System (Process)", "route": f"/start-process/{TEST_USER_ID}", "method": "POST", "desc": "Start fetch/post loop for user"},
    {"category": "System (Process)", "route": f"/stop-process/{TEST_USER_ID}", "method": "POST", "desc": "Stop fetch/post loop for user"},
    {"category": "Accounts", "route": "/api/accounts", "method": "GET", "desc": "List accounts & stats"},
    # {"category": "Accounts", "route": f"/api/account/{TEST_TWITTER_ID}", "method": "GET", "desc": "Get account details"},
    {"category": "Usage", "route": "/api/usage/requests-per-day", "method": "GET", "desc": "Aggregated daily API usage"},
    # Only test safe endpoints. avoid refresh-profile and email-today as they cost money or send emails.
]

results = []

for ep in endpoints:
    url = f"{BASE_URL}{ep['route']}"
    try:
        if ep["method"] == "GET":
            res = requests.get(url, timeout=5)
        else:
            res = requests.post(url, timeout=5)
            
        status = "PASS" if res.status_code in [200, 400, 404] else "FAIL"
        msg = f"{res.status_code}"
    except Exception as e:
        status = "ERROR"
        msg = str(e)
        
    results.append({
        "Category": ep["category"],
        "Route": ep["route"],
        "Method": ep["method"],
        "Status": status,
        "Code/Error": msg
    })

print("| Category | Route | Method | Status | Details |")
print("|---|---|---|---|---|")
for r in results:
    print(f"| {r['Category']} | `{r['Route']}` | {r['Method']} | {r['Status']} | {r['Code/Error']} |")
