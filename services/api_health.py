"""
API Health Check Service
Runs daily at 00:01 alongside the smart scheduler.
Tests all configured external APIs and logs results.
"""
import requests
import time
from datetime import datetime
from services.db_service import run_query


def get_api_key(key_id):
    result = run_query(f"SELECT key FROM api_keys WHERE id = {key_id}", fetchone=True)
    return result[0] if result else None


def check_rapidapi():
    key = get_api_key(3)
    if not key:
        return {"api": "RapidAPI (twttrapi)", "status": "misconfigured", "latency_ms": None, "error": "No key found"}
    start = time.time()
    try:
        res = requests.get(
            "https://twttrapi.p.rapidapi.com/user-info?username=twitter",
            headers={"x-rapidapi-key": key, "x-rapidapi-host": "twttrapi.p.rapidapi.com"},
            timeout=10
        )
        latency = int((time.time() - start) * 1000)
        status = "healthy" if res.status_code in [200, 201] else "degraded"
        return {"api": "RapidAPI (twttrapi)", "status": status, "latency_ms": latency, "http_code": res.status_code, "error": None}
    except Exception as e:
        return {"api": "RapidAPI (twttrapi)", "status": "down", "latency_ms": None, "error": str(e)}


def check_socialdata():
    key = get_api_key(2)
    if not key:
        return {"api": "SocialData", "status": "misconfigured", "latency_ms": None, "error": "No key found"}
    start = time.time()
    try:
        res = requests.get(
            "https://api.socialdata.tools/twitter/user/twitter",
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=10
        )
        latency = int((time.time() - start) * 1000)
        status = "healthy" if res.status_code in [200, 201] else "degraded"
        return {"api": "SocialData", "status": status, "latency_ms": latency, "http_code": res.status_code, "error": None}
    except Exception as e:
        return {"api": "SocialData", "status": "down", "latency_ms": None, "error": str(e)}


def check_openrouter():
    key = get_api_key(1)
    if not key:
        return {"api": "OpenRouter/OpenAI", "status": "misconfigured", "latency_ms": None, "error": "No key found"}
    start = time.time()
    try:
        res = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10
        )
        latency = int((time.time() - start) * 1000)
        status = "healthy" if res.status_code in [200, 201] else "degraded"
        # Try to get credit info
        credits = None
        try:
            data = res.json()
            # OpenRouter doesn't expose credits in model list, so we try the credits endpoint
            credits_res = requests.get(
                "https://openrouter.ai/api/v1/auth/key",
                headers={"Authorization": f"Bearer {key}"},
                timeout=5
            )
            if credits_res.status_code == 200:
                cdata = credits_res.json()
                credits = cdata.get("data", {}).get("limit_remaining")
        except Exception:
            pass
        return {"api": "OpenRouter/OpenAI", "status": status, "latency_ms": latency, "http_code": res.status_code, "credits_remaining": credits, "error": None}
    except Exception as e:
        return {"api": "OpenRouter/OpenAI", "status": "down", "latency_ms": None, "error": str(e)}


def check_twitterapi_io():
    key = get_api_key(5)
    if not key:
        return {"api": "TwitterAPI.io", "status": "misconfigured", "latency_ms": None, "error": "No key found"}
    start = time.time()
    try:
        res = requests.get(
            "https://api.twitterapi.io/twitter/user/info?userName=twitter",
            headers={"X-API-Key": key},
            timeout=10
        )
        latency = int((time.time() - start) * 1000)
        status = "healthy" if res.status_code in [200, 201] else "degraded"
        return {"api": "TwitterAPI.io", "status": status, "latency_ms": latency, "http_code": res.status_code, "error": None}
    except Exception as e:
        return {"api": "TwitterAPI.io", "status": "down", "latency_ms": None, "error": str(e)}


def run_health_check():
    """Run all API health checks and store results in api_health_log."""
    print("[APIHealth] Running full API health check...")
    results = [
        check_rapidapi(),
        check_socialdata(),
        check_openrouter(),
        check_twitterapi_io(),
    ]

    now = datetime.now().isoformat()
    for r in results:
        api_name = r.get("api", "unknown").replace("'", "")
        status = r.get("status", "unknown")
        latency = r.get("latency_ms")
        error = (r.get("error") or "").replace("'", "")[:500]
        credits = r.get("credits_remaining")

        latency_val = str(latency) if latency is not None else "NULL"
        credits_val = f"'{credits}'" if credits is not None else "NULL"

        run_query(
            f"INSERT INTO api_health_log (api_name, status, latency_ms, credits_remaining, error_message, checked_at) "
            f"VALUES ('{api_name}', '{status}', {latency_val}, {credits_val}, '{error}', '{now}')"
        )

    print(f"[APIHealth] Completed health check. Results: {[r['status'] for r in results]}")
    return results


def get_latest_health():
    """Return the latest health status for each API."""
    rows = run_query(
        "SELECT DISTINCT ON (api_name) api_name, status, latency_ms, credits_remaining, error_message, checked_at "
        "FROM api_health_log ORDER BY api_name, checked_at DESC"
    )
    if not rows:
        return []
    result = []
    for row in rows:
        result.append({
            "api": row[0],
            "status": row[1],
            "latency_ms": row[2],
            "credits_remaining": row[3],
            "error": row[4],
            "checked_at": row[5].isoformat() if row[5] else None
        })
    return result
