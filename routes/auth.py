from flask import Blueprint, redirect, request, session, url_for, jsonify
from requests_oauthlib import OAuth1Session
from services.db_service import run_query
from config import Config
import requests
import logging
from routes.logs import log_usage

auth_bp = Blueprint("auth", __name__)

REQUEST_TOKEN_URL = "https://api.twitter.com/oauth/request_token"
AUTHORIZATION_URL = "https://api.twitter.com/oauth/authenticate"
ACCESS_TOKEN_URL = "https://api.twitter.com/oauth/access_token"
CALLBACK_URL = "http://localhost:5000/auth/callback" 

def get_rapidapi_key():
    query = "SELECT key FROM api_keys WHERE id = 3" 
    result = run_query(query, fetchone=True)
    return result[0] if result else None


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect("http://localhost:3000"), 200


@auth_bp.route("/save-user", methods=["POST"])
def save_user():
    try:
        data = request.get_json()
        twitter_id = data.get("twitter_id")
        username = data.get("username")
        password = data.get("password") 
        session_token = data.get("session")

        if not twitter_id or not session_token:
            return jsonify({"success": False, "message": "twitter_id y session son obligatorios"}), 400

        query = f"""
        INSERT INTO users (twitter_id, username, password, session)
        VALUES ('{twitter_id}', '{username}', {'NULL' if password is None else f"'{password}'"}, '{session_token}')
        ON CONFLICT (twitter_id) DO UPDATE
        SET username = '{username}', session = '{session_token}'
        RETURNING id;
        """

        user_id = run_query(query, fetchone=True)

        if user_id:
            return jsonify({"success": True, "user_id": user_id[0]}), 201
        else:
            return jsonify({"success": False, "message": "Error al guardar usuario"}), 500

    except Exception as e:
        print(f"❌ Error en /save-user: {e}")
        return jsonify({"success": False, "message": "Error en el servidor"}), 500


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "Missing Data"}), 400

    rapidapi_key = get_rapidapi_key()
    if not rapidapi_key:
        return jsonify({"error": "Can't find RapidAPI Key"}), 500

    url = "https://twttrapi.p.rapidapi.com/login-email-username"
    headers = {
        "x-rapidapi-key": rapidapi_key,
        "x-rapidapi-host": "twttrapi.p.rapidapi.com",
        "Content-Type": "application/x-www-form-urlencoded",
        # 'twttr-proxy': "http://sp4tntbmfv:+lRkdu4bE0E2ecn9uH@ar.smartproxy.com:10001"
    }
    payload = {
        "username_or_email": username,
        "password": password,
        "flow_name": "LoginFlow"
    }

    try:
        response = requests.post(url, headers=headers, data=payload)
        log_usage("RAPIDAPI")
        response_data = response.json()

        if response.status_code == 200 and response_data.get("success"):
            return jsonify(response_data), 200
        elif response_data.get("hint") == "Please use second endpoint /login_2fa to continue login.":
            return jsonify({"error": "2FA_REQUIRED", "login_data": response_data.get("login_data")}), 401
        else:
            print(response_data)
            return jsonify({"error": response_data.get("message", "Login failed")}), response.status_code

    except Exception as e:
        logging.error(f"❌ RapidAPI Error: {str(e)}")
        return jsonify({"error": "Server Error"}), 500


@auth_bp.route("/login-2fa", methods=["POST"])
def login_2fa():
    data = request.json
    login_data = data.get("login_data")
    otp = data.get("otp")

    if not login_data or not otp:
        return jsonify({"error": "Missing Data"}), 400

    rapidapi_key = get_rapidapi_key()
    if not rapidapi_key:
        return jsonify({"error": "Can't find RapidAPI Key"}), 500

    url = "https://twttrapi.p.rapidapi.com/login-2fa"
    headers = {
        "x-rapidapi-key": rapidapi_key,
        "x-rapidapi-host": "twttrapi.p.rapidapi.com",
        "Content-Type": "application/x-www-form-urlencoded",
        # 'twttr-proxy': "http://sp4tntbmfv:+lRkdu4bE0E2ecn9uH@ar.smartproxy.com:10001"
    }
    payload = {
        "login_data": login_data,
        "response": otp
    }

    try:
        response = requests.post(url, headers=headers, data=payload)
        log_usage("RAPIDAPI")
        response_data = response.json()

        if response.status_code == 200 and response_data.get("success"):
            return jsonify(response_data), 200
        else:
            return jsonify({"error": response_data.get("message", "Invalid Code")}), response.status_code

    except Exception as e:
        logging.error(f"❌ RapidAPI Error (2FA): {str(e)}")
        return jsonify({"error": "Server Error"}), 500


@auth_bp.route("/generate-totp", methods=["POST"])
def generate_totp():
    """Generate a TOTP code from a given 2FA secret (same algorithm as 2fa.live)."""
    try:
        import pyotp
        data = request.json
        secret = data.get("secret", "").strip().replace(" ", "")
        if not secret:
            return jsonify({"error": "2FA secret is required"}), 400
        totp = pyotp.TOTP(secret)
        code = totp.now()
        return jsonify({"code": code, "valid_for_seconds": totp.interval - (int(__import__("time").time()) % totp.interval)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@auth_bp.route("/bulk-login", methods=["POST"])
def bulk_login():
    """
    Accepts an array of account credentials and logs them in one by one.
    Each item: {username, password, twofa_secret, label}
    Returns a per-account result log.
    """
    import pyotp
    data = request.json
    accounts = data.get("accounts", [])
    if not accounts:
        return jsonify({"error": "No accounts provided"}), 400

    rapidapi_key = get_rapidapi_key()
    if not rapidapi_key:
        return jsonify({"error": "Can't find RapidAPI Key"}), 500

    results = []
    for acc in accounts:
        username = acc.get("username", "").strip()
        password = acc.get("password", "").strip()
        twofa_secret = acc.get("twofa_secret", "").strip().replace(" ", "")
        label = acc.get("label", username)

        if not username or not password:
            results.append({"username": username, "label": label, "status": "skipped", "error": "Missing username or password"})
            continue

        try:
            # Step 1: Login
            login_url = "https://twttrapi.p.rapidapi.com/login-email-username"
            headers = {
                "x-rapidapi-key": rapidapi_key,
                "x-rapidapi-host": "twttrapi.p.rapidapi.com",
                "Content-Type": "application/x-www-form-urlencoded",
            }
            payload = {"username_or_email": username, "password": password, "flow_name": "LoginFlow"}
            response = requests.post(login_url, headers=headers, data=payload)
            log_usage("RAPIDAPI")
            response_data = response.json()

            session_token = None
            twitter_id = None

            if response.status_code == 200 and response_data.get("success"):
                # Direct login success — no 2FA needed
                session_token = response_data.get("session") or response_data.get("auth_token")
                twitter_id = response_data.get("user_id") or response_data.get("id")

            elif response_data.get("hint") == "Please use second endpoint /login_2fa to continue login." and twofa_secret:
                # 2FA required — generate TOTP and complete login
                login_data = response_data.get("login_data")
                totp = pyotp.TOTP(twofa_secret)
                otp = totp.now()

                fa_url = "https://twttrapi.p.rapidapi.com/login-2fa"
                fa_payload = {"login_data": login_data, "response": otp}
                fa_response = requests.post(fa_url, headers=headers, data=fa_payload)
                log_usage("RAPIDAPI")
                fa_data = fa_response.json()

                if fa_response.status_code == 200 and fa_data.get("success"):
                    session_token = fa_data.get("session") or fa_data.get("auth_token")
                    twitter_id = fa_data.get("user_id") or fa_data.get("id")
                else:
                    results.append({"username": username, "label": label, "status": "failed", "error": fa_data.get("message", "2FA failed")})
                    continue
            else:
                results.append({"username": username, "label": label, "status": "failed", "error": response_data.get("message", "Login failed")})
                continue

            if session_token and twitter_id:
                # Upsert into users table
                username_safe = username.replace("'", "")
                run_query(
                    f"INSERT INTO users (twitter_id, username, password, session, account_status) "
                    f"VALUES ('{twitter_id}', '{username_safe}', '{password.replace(chr(39), '')}', '{session_token}', 'active') "
                    f"ON CONFLICT (twitter_id) DO UPDATE SET session = '{session_token}', account_status = 'active', username = '{username_safe}'"
                )
                if twofa_secret:
                    run_query(f"UPDATE users SET twofa_secret = '{twofa_secret}' WHERE twitter_id = '{twitter_id}'")
                results.append({"username": username, "label": label, "status": "success", "twitter_id": str(twitter_id)})
            else:
                results.append({"username": username, "label": label, "status": "failed", "error": "No session returned"})

        except Exception as e:
            results.append({"username": username, "label": label, "status": "error", "error": str(e)})

    return jsonify({"results": results}), 200


@auth_bp.route("/relogin/<string:twitter_id>", methods=["POST"])
def relogin_account(twitter_id):
    """Re-login a specific account using stored credentials and 2FA secret."""
    import pyotp
    user_row = run_query(
        f"SELECT username, password, twofa_secret FROM users WHERE twitter_id = '{twitter_id}'",
        fetchone=True
    )
    if not user_row:
        return jsonify({"error": "Account not found"}), 404

    username, password, twofa_secret = user_row
    if not username or not password:
        return jsonify({"error": "No stored credentials for this account"}), 400

    rapidapi_key = get_rapidapi_key()
    if not rapidapi_key:
        return jsonify({"error": "Can't find RapidAPI Key"}), 500

    try:
        login_url = "https://twttrapi.p.rapidapi.com/login-email-username"
        headers = {
            "x-rapidapi-key": rapidapi_key,
            "x-rapidapi-host": "twttrapi.p.rapidapi.com",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        payload = {"username_or_email": username, "password": password, "flow_name": "LoginFlow"}
        response = requests.post(login_url, headers=headers, data=payload)
        log_usage("RAPIDAPI")
        response_data = response.json()
        session_token = None

        if response.status_code == 200 and response_data.get("success"):
            session_token = response_data.get("session") or response_data.get("auth_token")
        elif response_data.get("hint") == "Please use second endpoint /login_2fa to continue login." and twofa_secret:
            login_data = response_data.get("login_data")
            totp = pyotp.TOTP(twofa_secret)
            otp = totp.now()
            fa_url = "https://twttrapi.p.rapidapi.com/login-2fa"
            fa_response = requests.post(fa_url, headers=headers, data={"login_data": login_data, "response": otp})
            log_usage("RAPIDAPI")
            fa_data = fa_response.json()
            if fa_response.status_code == 200 and fa_data.get("success"):
                session_token = fa_data.get("session") or fa_data.get("auth_token")
            else:
                return jsonify({"error": fa_data.get("message", "2FA re-login failed")}), 400
        else:
            return jsonify({"error": response_data.get("message", "Re-login failed")}), 400

        if session_token:
            run_query(
                f"UPDATE users SET session = '{session_token}', account_status = 'active', consecutive_failures = 0 "
                f"WHERE twitter_id = '{twitter_id}'"
            )
            return jsonify({"success": True, "message": "Re-login successful"}), 200
        else:
            return jsonify({"error": "No session returned"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500