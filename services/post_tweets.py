import requests
from services.db_service import run_query, log_event
import logging
from routes.logs import log_usage
import uuid
from urllib.parse import urlparse
from supabase import create_client
import httpx
import mimetypes
import re
from utils.logs import now_hhmm

logging.basicConfig(level=logging.INFO)

mimetypes.add_type("video/quicktime", ".mov")
mimetypes.add_type("video/x-msvideo", ".avi")
mimetypes.add_type("video/x-matroska", ".mkv")
mimetypes.add_type("video/webm", ".webm")
mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/png", ".png")
mimetypes.add_type("image/jpeg", ".jpg")
mimetypes.add_type("image/gif", ".gif")

import os
SUPABASE_URL = "https://srgkjdgxdzqxflleqkse.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
BUCKET_NAME = "images"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_extraction_filter(user_id):
    query = f"SELECT extraction_filter FROM users WHERE id = {user_id}"  
    result = run_query(query, fetchone=True)
    return result[0] if result else None 


def get_twitterapi_key():
    query = "SELECT key FROM api_keys WHERE id = 5"
    result = run_query(query, fetchone=True)
    return result[0] if result else "6f60bb14a3ff43d59daf70cf2857d1c3"

def delete_from_supabase(path):
    try:
        if not path:
            return
        supabase.storage.from_(BUCKET_NAME).remove([path])
        print(f"🗑️ Archivo eliminado de Supabase: {path}")
    except Exception as e:
        print(f"⚠️ No se pudo borrar de Supabase: {e}")


def post_tweet(user_id, tweet_text, media_urls=None):
    if len(tweet_text) > 280:
        print(f"⚠️ Tweet demasiado largo ({len(tweet_text)} caracteres).")
        # TwitterAPI.io might support longer, but let's warn.
    
    api_key = get_twitterapi_key()
    if not api_key:
        return {"error": "No se pudo obtener la API Key de TwitterAPI.io"}, 500

    if isinstance(tweet_text, list):
        tweet_text = " ".join(tweet_text)
    
    # Check for media (TwitterAPI.io media upload is separate, for now we handle text)
    # If we have media_urls, we might need to use their media endpoint. 
    # For this migration step, I will focus on the text Post.
    # TODO: Implement media upload for TwitterAPI.io if documentation allows.
    
    session_row = run_query(f"SELECT session FROM users WHERE id = {user_id}", fetchone=True)
    auth_session = session_row[0] if session_row else None
    
    if not auth_session:
        return {"error": "No auth_session found for user"}, 400

    url = "https://api.twitterapi.io/twitter/create_tweet"
    payload = {
        "tweet_text": tweet_text,
        "auth_session": auth_session,
        "proxy": "http://sp4tntbmfv:+lRkdu4bE0E2ecn9uH@ar.smartproxy.com:10001"
    }
    
    # If media_ids were supported/implemented:
    # payload['media'] = {"media_ids": [...]}

    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        log_usage("TWITTERAPI.IO")
        
        if response.status_code == 200:
            data = response.json()
            print("TwitterAPI.io Response:", data)
            
            # Check for API-level errors returned as 200 OK
            if data.get("success") is False or data.get("status") == "error":
                error_msg = data.get("error") or data.get("msg") or "Unknown API error"
                print(f"❌ Error posting tweet: {error_msg}")
                return {"error": f"Failed to post: {error_msg}"}, 400
                
            # Try to extract ID
            tweet_id = data.get("data", {}).get("id")
            if not tweet_id:
                tweet_id = data.get("id") # Fallback
            
            tweet_url = f"https://twitter.com/user/status/{tweet_id}" # We might not know screen_name immediately
            
            # Log success
            try:
                username_row = run_query(f"SELECT username FROM users WHERE id = {user_id}", fetchone=True)
                username = username_row[0] if username_row else f"User {user_id}"
                log_event(user_id, "POSTED", f"@{username} posted via TwitterAPI.io: {tweet_text[:30]}...")
            except Exception:
                pass

            return {"message": "Tweet posted successfully", "tweet_id": tweet_id, "tweet_url": tweet_url}, 200
        else:
            print(f"❌ Error posting tweet: {response.status_code} - {response.text}")
            return {"error": f"Failed to post: {response.text}"}, response.status_code

    except Exception as e:
        print(f"❌ Exception posting tweet: {e}")
        return {"error": str(e)}, 500
