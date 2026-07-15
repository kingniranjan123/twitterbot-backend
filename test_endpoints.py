import subprocess
import time
import requests

# Start the Flask app
print("Starting Flask server...")
proc = subprocess.Popen(["python", "app.py"])
time.sleep(5)  # Wait for server to start

BASE_URL = "http://localhost:5000"

endpoints_to_test = [
    ("GET", "/", None),
    ("GET", "/status-fetch", None),
    ("POST", "/start-fetch", None),
    ("POST", "/stop-fetch", None),
    ("GET", "/api/accounts", None),
    ("GET", "/api/account/dummy_id", None),
    ("POST", "/api/account/dummy_id/refresh-profile", None),
    ("POST", "/api/account/dummy_id/verify-category", None),
    ("GET", "/api/usage/requests-per-day", None),
    ("GET", "/api/openai-config?user_id=dummy", None),
]

print(f"{'Method':<8} | {'Endpoint':<45} | {'Status'}")
print("-" * 65)

for method, path, data in endpoints_to_test:
    url = f"{BASE_URL}{path}"
    try:
        if method == "GET":
            resp = requests.get(url, timeout=5)
        elif method == "POST":
            resp = requests.post(url, json=data, timeout=5)
        elif method == "PUT":
            resp = requests.put(url, json=data, timeout=5)
        elif method == "DELETE":
            resp = requests.delete(url, timeout=5)
            
        print(f"{method:<8} | {path:<45} | {resp.status_code}")
    except Exception as e:
        print(f"{method:<8} | {path:<45} | ERROR: {e}")

print("-" * 65)
print("Stopping Flask server...")
proc.terminate()
try:
    proc.wait(timeout=5)
except:
    proc.kill()
print("Done.")
