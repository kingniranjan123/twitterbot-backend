import asyncio
import aiohttp
from services.db_service import run_query, log_event
from services.ai_service import save_collected_tweet, generate_reply_with_openai, generate_post_with_openai, save_collected_tweet_simple
from datetime import datetime, timezone, timedelta
from services.post_tweets import post_tweet
import time
from routes.logs import log_usage
import itertools
import re
from googleapiclient.discovery import build
from google.oauth2 import service_account
import json
from time import monotonic
import random
from weakref import WeakKeyDictionary
from asyncio import AbstractEventLoop

SOCIALDATA_API_URL = "https://api.socialdata.tools/twitter/search"
TWEET_LIMIT_PER_HOUR = 50
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Per-event-loop rate-limit state to avoid cross-loop Lock errors
_TWAPI_LOCK_BY_LOOP: "WeakKeyDictionary[AbstractEventLoop, asyncio.Lock]" = WeakKeyDictionary()
_TWAPI_LAST_CALL_BY_LOOP: "WeakKeyDictionary[AbstractEventLoop, float]" = WeakKeyDictionary()
_TWAPI_429_STREAK_BY_LOOP: "WeakKeyDictionary[AbstractEventLoop, int]" = WeakKeyDictionary()
_TWAPI_INTERVAL = 2.2   # más margen por Cloudflare
_TWAPI_429_STREAK_FOR_COOLDOWN = 2
_TWAPI_COOLDOWN_429 = 60
_TWAPI_JITTER_MIN = 0.05
_TWAPI_JITTER_MAX = 0.25
TWITTERAPI_URL = "https://api.twitterapi.io/twitter/tweet/advanced_search"

def _get_running_loop() -> AbstractEventLoop:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        # Fallback for contexts without a running loop yet
        return asyncio.get_event_loop()

def _get_twapi_rate_state():
    """
    Returns the loop-specific lock and ensures counters exist for that loop.
    """
    loop = _get_running_loop()
    lock = _TWAPI_LOCK_BY_LOOP.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _TWAPI_LOCK_BY_LOOP[loop] = lock
        _TWAPI_LAST_CALL_BY_LOOP[loop] = 0.0
        _TWAPI_429_STREAK_BY_LOOP[loop] = 0
    return loop, lock


def _retry_after_seconds(headers) -> int | None:
    try:
        ra = headers.get("Retry-After")
        return int(ra) if ra is not None else None
    except Exception:
        return None

async def _twapi_one_request(session, headers, params, timeout=60):
    loop, lock = _get_twapi_rate_state()
    async with lock:
        now = monotonic()
        last_call = _TWAPI_LAST_CALL_BY_LOOP.get(loop, 0.0)
        wait = _TWAPI_INTERVAL - (now - last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        # jitter leve para no caer en bordes de ventana
        await asyncio.sleep(random.uniform(_TWAPI_JITTER_MIN, _TWAPI_JITTER_MAX))

        async with session.get(TWITTERAPI_URL, headers=headers, params=params, timeout=timeout) as resp:
            status = resp.status
            hdrs = resp.headers
            try:
                payload = await resp.json()
            except Exception:
                payload = None

        _TWAPI_LAST_CALL_BY_LOOP[loop] = monotonic()
    return status, hdrs, payload

async def twapi_request(session, headers, params, timeout=60, max_retries=6):
    """Rate limit global, Retry-After, backoff exponencial con cooldown por racha."""
    loop, _ = _get_twapi_rate_state()
    attempt = 0
    while True:
        status, hdrs, payload = await _twapi_one_request(session, headers, params, timeout=timeout)
        if status != 429:
            _TWAPI_429_STREAK_BY_LOOP[loop] = 0
            return status, hdrs, payload

        current_streak = _TWAPI_429_STREAK_BY_LOOP.get(loop, 0) + 1
        _TWAPI_429_STREAK_BY_LOOP[loop] = current_streak

        ra = _retry_after_seconds(hdrs)
        if ra and ra > 0:
            print(f"⏳ 429, Retry-After {ra}s")
            await asyncio.sleep(ra)
        else:
            base, factor, cap = 2.2, 2.0, 120
            sleep_s = min(cap, base * (factor ** attempt)) + random.uniform(0, 0.6)
            print(f"⏳ 429, backoff try {attempt+1}, sleep {sleep_s:.1f}s")
            await asyncio.sleep(sleep_s)

        if _TWAPI_429_STREAK_BY_LOOP.get(loop, 0) >= _TWAPI_429_STREAK_FOR_COOLDOWN:
            print(f"🧊 Cooldown global por racha de 429, {_TWAPI_COOLDOWN_429}s")
            await asyncio.sleep(_TWAPI_COOLDOWN_429)
            _TWAPI_429_STREAK_BY_LOOP[loop] = 0

        attempt += 1
        if attempt > max_retries:
            print("🚫 429 persistente, abandono esta página")
            return status, hdrs, payload


def get_google_json():
    query = "SELECT json FROM api_keys WHERE id = 4"  
    result = run_query(query, fetchone=True)
    return result[0] if result else None  


def get_drive_service():
    json_string = get_google_json()
    if not json_string:
        raise ValueError("❌ No se encontró la clave del Service Account en la base de datos.")

    credentials_data = json.loads(json_string)

    creds = service_account.Credentials.from_service_account_info(
        credentials_data,
        scopes=SCOPES
    )

    return build("drive", "v3", credentials=creds)


def extract_folder_id(url):
    match = re.search(r"/folders/([a-zA-Z0-9_-]+)", url)
    return match.group(1) if match else None


def extract_base_name(filename):
    return re.sub(r'_\d+(?=\.\w+$)', '', filename)


def get_socialdata_api_key():
    query = "SELECT key FROM api_keys WHERE id = 2"  
    result = run_query(query, fetchone=True)
    return result[0] if result else None 


def get_extraction_filter(user_id):
    query = f"SELECT extraction_filter FROM users WHERE id = {user_id}"  
    result = run_query(query, fetchone=True)
    return result[0] if result else None 


def get_rapidapi_key():
    query = "SELECT key FROM api_keys WHERE id = 3" 
    result = run_query(query, fetchone=True)
    return result[0] if result else None  


async def get_tweet_limit_per_hour(user_id):
    query = f"SELECT rate_limit FROM users WHERE id = {user_id}"
    result = run_query(query, fetchone=True)
    try:
        return int(result[0]) if result and result[0] is not None else 10
    except (ValueError, TypeError):
        return 10


def get_extraction_method(user_id):
    query = f"SELECT extraction_method FROM users WHERE id = {user_id}"
    result = run_query(query, fetchone=True)
    return result[0] if result else 1


def get_like_limit_per_hour(user_id):
    result = run_query(f"SELECT likes_limit FROM users WHERE id = {user_id}", fetchone=True)
    try:
        return int(result[0]) if result and result[0] is not None else 1
    except (ValueError, TypeError):
        return 1


def get_comment_limit_per_hour(user_id):
    result = run_query(f"SELECT comments_limit FROM users WHERE id = {user_id}", fetchone=True)
    try:
        return int(result[0]) if result and result[0] is not None else 1
    except (ValueError, TypeError):
        return 1


def get_follow_limit_per_hour(user_id):
    result = run_query(f"SELECT follows_limit FROM users WHERE id = {user_id}", fetchone=True)
    try:
        return int(result[0]) if result and result[0] is not None else 1
    except (ValueError, TypeError):
        return 1


def get_retweet_limit_per_hour(user_id):
    result = run_query(f"SELECT retweets_limit FROM users WHERE id = {user_id}", fetchone=True)
    try:
        return int(result[0]) if result and result[0] is not None else 1
    except (ValueError, TypeError):
        return 1


async def count_tweets_for_user(user_id):
    query = f"""
    SELECT COUNT(*) FROM posted_tweets 
    WHERE user_id = {user_id}
    AND created_at >= NOW() - INTERVAL '1 hour'
    """
    result = run_query(query, fetchone=True)
    return result[0] if result else 0


async def count_tweets_for_user2(user_id):
    query = f"""
    SELECT COUNT(*) FROM collected_tweets 
    WHERE user_id = {user_id}
    AND created_at >= NOW() - INTERVAL '1 hour'
    """
    result = run_query(query, fetchone=True)
    return result[0] if result else 0


def get_search_api():
    query = "SELECT value FROM global_config WHERE id = 1"
    result = run_query(query, fetchone=True)
    return result[0] if result else None


def get_twitterapi_key():
    query = "SELECT key FROM api_keys WHERE id = 5"
    result = run_query(query, fetchone=True)
    # Return DB key or the User provided key as fallback
    return result[0] if result else "6f60bb14a3ff43d59daf70cf2857d1c3"


def _format_since_for_twitterapi_io(ts_unix: int) -> str:
    dt = datetime.fromtimestamp(ts_unix, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d_%H:%M:%S_UTC")

def _get_since_timestamp_for_user(user_id):
    last_extract_row = run_query(f"SELECT MAX(timestamp) FROM logs WHERE user_id = '{user_id}' AND event_type = 'EXTRACT'", fetchone=True)
    import time
    if last_extract_row and last_extract_row[0]:
        last_extract_dt = last_extract_row[0]
        if last_extract_dt.tzinfo is None:
            last_extract_dt = last_extract_dt.replace(tzinfo=timezone.utc)
        else:
            last_extract_dt = last_extract_dt.astimezone(timezone.utc)
        since_timestamp = int(last_extract_dt.timestamp())
        
        # Max lookback: 24 hours
        min_lookback = int(time.time()) - 24 * 60 * 60
        if since_timestamp < min_lookback:
            return min_lookback
        # Overlap by 60 seconds to avoid missing border tweets
        return since_timestamp - 60
    else:
        return int(time.time()) - 24 * 60 * 60

async def extract_by_combination(session, user_id, monitored_users, keywords, limit, fetching_event):
    since_timestamp = _get_since_timestamp_for_user(user_id)
    collected_count = 0

    api_key = get_twitterapi_key()
    if not api_key:
        print("❌ No se pudo obtener la API Key de TwitterAPI.io.")
        return 0

    headers = {
        "X-API-Key": api_key,
        "Accept": "application/json",
        "User-Agent": "twitter-bot/1.0"
    }

    combinaciones = list(itertools.product(monitored_users, keywords))
    since_str = _format_since_for_twitterapi_io(since_timestamp)

    for username, keyword in combinaciones:
        if fetching_event.is_set():
            print("⏹️ Proceso detenido mientras recorría combinaciones.")
            return collected_count

        if collected_count >= limit:
            return collected_count

        base = f'from:{username} ({keyword}) since:{since_str}'
        extraction_filter = get_extraction_filter(user_id)

        query = f"({base})"
        if extraction_filter == "cb2":
            query = f"({base} filter:images)"
        elif extraction_filter == "cb3":
            query = f"({base} filter:native_video)"
        elif extraction_filter == "cb4":
            query = f"({base} filter:media)"
        elif extraction_filter == "cb5":
            query = f"({base} filter:images -filter:videos)"
        elif extraction_filter == "cb6":
            query = f"({base} -filter:images -filter:videos -filter:links)"

        print(f"🔎 Consultando: {query}")

        cursor = ""
        while True:
            if fetching_event.is_set() or collected_count >= limit:
                return collected_count

            params = {
                "query": query,
                "queryType": "Latest",
                "cursor": cursor,
            }

            try:
                # usa helper con lock global y backoff para 429
                status, hdrs, payload = await twapi_request(
                    session,
                    headers,
                    params,
                    timeout=60
                )

                if status != 200:
                    print(f"❌ Error {status} en TwitterAPI.io para: {query} cursor={cursor}")
                    log_usage("TWITTERAPI.IO", count=1)
                    break

                tweets = (payload or {}).get("tweets", []) or []
                has_next = (payload or {}).get("has_next_page", False)
                next_cursor = (payload or {}).get("next_cursor", "")

                log_usage("TWITTERAPI.IO", count=len(tweets))

                if not tweets:
                    break

                for t in tweets:
                    if fetching_event.is_set() or collected_count >= limit:
                        return collected_count

                    tweet_id = t.get("id")
                    tweet_text = t.get("text")
                    created_at = t.get("createdAt")

                    save_collected_tweet(
                        user_id,
                        "combined",
                        None,
                        tweet_id,
                        tweet_text,
                        created_at,
                        extraction_filter,
                    )
                    collected_count += 1

                if not has_next or not next_cursor:
                    break

                cursor = next_cursor

            except Exception as e:
                print(f"❌ Excepción consultando TwitterAPI.io para {query}: {e}")
                break

    return collected_count


async def extract_by_copy_user(session, user_id, monitored_users, limit, fetching_event):
    since_timestamp = _get_since_timestamp_for_user(user_id)
    collected_count = 0

    api_key = get_twitterapi_key()
    if not api_key:
        print("❌ No se pudo obtener la API Key de TwitterAPI.io.")
        return 0

    headers = {
        "X-API-Key": api_key,
        "Accept": "application/json",
        "User-Agent": "twitter-bot/1.0"
    }
    since_str = _format_since_for_twitterapi_io(since_timestamp)
    extraction_filter = get_extraction_filter(user_id)

    for username in monitored_users:
        if fetching_event.is_set():
            print("⏹️ Proceso detenido mientras recorría usuarios.")
            return collected_count
        if collected_count >= limit:
            print(f"✅ Límite alcanzado: {collected_count}/{limit}")
            return collected_count

        base = f"from:{username} since:{since_str}"
        if extraction_filter == "cb2":
            query = f"({base} filter:images)"
        elif extraction_filter == "cb3":
            query = f"({base} filter:native_video)"
        elif extraction_filter == "cb4":
            query = f"({base} filter:media)"
        elif extraction_filter == "cb5":
            query = f"({base} filter:images -filter:videos)"
        elif extraction_filter == "cb6":
            query = f"({base} -filter:images -filter:videos -filter:links)"
        else:
            query = f"({base})"

        print(f"🔎 Consultando: {query}")

        cursor = ""
        while True:
            if fetching_event.is_set() or collected_count >= limit:
                return collected_count

            params = {
                "query": query,
                "queryType": "Latest",
                "cursor": cursor,
            }

            try:
                status, hdrs, payload = await twapi_request(
                    session=session,
                    headers=headers,
                    params=params,
                    timeout=60
                )

                if status != 200:
                    print(f"❌ Error {status} en TwitterAPI.io para @{username}, cursor={cursor}")
                    log_usage("TWITTERAPI.IO", count=1)
                    break

                tweets = (payload or {}).get("tweets", []) or []
                has_next = (payload or {}).get("has_next_page", False)
                next_cursor = (payload or {}).get("next_cursor", "")

                log_usage("TWITTERAPI.IO", count=len(tweets))

                if not tweets:
                    print(f"⚠️ No se encontraron tweets para @{username} en esta página")
                    break

                for t in tweets:
                    if fetching_event.is_set() or collected_count >= limit:
                        return collected_count

                    tweet_id = t.get("id")
                    tweet_text = t.get("text")
                    created_at = t.get("createdAt")

                    save_collected_tweet(
                        user_id,
                        "full_account_copy",
                        username,
                        tweet_id,
                        tweet_text,
                        created_at,
                        extraction_filter
                    )
                    collected_count += 1
                    print(f"💾 Tweet guardado de @{username}: {tweet_id}")

                if not has_next or not next_cursor:
                    break
                cursor = next_cursor

            except Exception as e:
                print(f"❌ Excepción consultando TwitterAPI.io para @{username}: {e}")
                break

    print(f"🎯 Extracción completa. Total tweets: {collected_count}/{limit}")
    return collected_count
    

async def fetch_tweets_for_monitored_users_with_keywords(session, user_id, monitored_users, keywords, limit, fetching_event, extraction_method):
    try:
        if fetching_event.is_set():
            return

        print(f"🎯 Ejecutando extracción para método {extraction_method}")

        initial_count_row = run_query(f"SELECT COUNT(*) FROM collected_tweets WHERE user_id = {user_id}", fetchone=True)
        initial_saved_count = initial_count_row[0] if initial_count_row else 0
        count = 0

        if extraction_method == 1:
            count = await extract_by_combination(session, user_id, monitored_users, keywords, limit, fetching_event)

        elif extraction_method == 2:
            count = await extract_by_copy_user(session, user_id, monitored_users, limit, fetching_event)

        elif extraction_method == 3:
            drive_link = run_query(f"SELECT drive_link FROM users WHERE id = {user_id}", fetchone=True)
            if not drive_link or not drive_link[0]:
                print(f"⚠️ Usuario {user_id} no tiene drive_link configurado.")
                return

            folder_id = extract_folder_id(drive_link[0])
            if not folder_id:
                print(f"❌ No se pudo extraer folder_id del link: {drive_link[0]}")
                return

            count = await extract_from_drive_link(user_id, folder_id, drive_link[0])

        else:
            print(f"⚠️ Método de extracción desconocido: {extraction_method}")
            return

        print(f"🎯 Finalizado. Total tweets extraídos: {count}/{limit}")
        
        final_count_row = run_query(f"SELECT COUNT(*) FROM collected_tweets WHERE user_id = {user_id}", fetchone=True)
        final_saved_count = final_count_row[0] if final_count_row else 0
        
        saved_count = max(0, final_saved_count - initial_saved_count)
        fetched_count = count
        rejected_count = max(0, fetched_count - saved_count)
        status = "SUCCESS"
        
        # LOGGING EXTRACT STATS
        try:
            username_row = run_query(f"SELECT username FROM users WHERE id = {user_id}", fetchone=True)
            username = username_row[0] if username_row else f"User {user_id}"
            
            from services.db_service import log_api_operation
            log_api_operation(user_id, username, "EXTRACT", status, fetched_count, saved_count, rejected_count, 0, "TwitterAPI", None)
            
            log_event(user_id, "EXTRACT", f"{username} extracted {count} posts at {datetime.now().strftime('%H:%M')}")
        except Exception as log_err:
            print(f"⚠️ Error logging extract stats: {log_err}")

    except asyncio.CancelledError:
        print(f"⏹️ Tarea cancelada para usuario ID: {user_id}.")
        raise
    except Exception as e:
        log_event(user_id, "ERROR", f"Error obteniendo tweets: {str(e)}")
        try:
            username_row = run_query(f"SELECT username FROM users WHERE id = {user_id}", fetchone=True)
            username = username_row[0] if username_row else f"User {user_id}"
            from services.db_service import log_api_operation
            log_api_operation(user_id, username, "EXTRACT", "FAILED", 0, 0, 0, 0, "TwitterAPI", str(e))
        except:
            pass
        print(f"❌ Error al buscar tweets: {e}")


async def fetch_tweets_for_single_user(user_id, fetching_event):
    print(f"🔍 Iniciando búsqueda de tweets para usuario ID: {user_id}...")

    if fetching_event.is_set():
        print(f"⏹️ Proceso detenido para usuario ID: {user_id}.")
        return

    query_users = f"SELECT DISTINCT twitter_username FROM monitored_users WHERE user_id = '{user_id}'"
    monitored_users = run_query(query_users, fetchall=True) or []

    query_keywords = f"SELECT DISTINCT keyword FROM user_keywords WHERE user_id = '{user_id}'"
    monitored_keywords = run_query(query_keywords, fetchall=True) or []
    extraction_method = get_extraction_method(user_id)

    if extraction_method != 3:
        if not monitored_users:
            print(f"⚠ Usuario {user_id} no tiene usuarios o palabras clave monitoreadas.")
            return

    limit_ph = await get_tweet_limit_per_hour(user_id)
    limit = round(limit_ph * 1.3)
    
    async with aiohttp.ClientSession() as session:
        await fetch_tweets_for_monitored_users_with_keywords(
            session,
            user_id,
            [user[0] for user in monitored_users],
            [keyword[0] for keyword in monitored_keywords],
            limit,
            fetching_event,
            extraction_method
        )

    print(f"✅ Búsqueda de tweets completada para usuario ID: {user_id}.")
    
    
async def fetch_tweets_for_all_users(fetching_event):
    print("🔍 Buscando tweets para cada usuario registrado (etapa 1)...")

    query = "SELECT DISTINCT id FROM users"
    users = run_query(query, fetchall=True)

    if not isinstance(users, (list, tuple)) or len(users) == 0:
        print("⚠ No hay usuarios registrados en la base de datos.")
        return
    
    users = [u for u in users if u and isinstance(u, (list, tuple)) and len(u) > 0 and u[0] is not None]

    tasks = []
    for user_id in users:
        if fetching_event.is_set():
            print("⏹️ Proceso detenido por solicitud de usuario.")
            return

        print(f"👤 Iniciando búsqueda de tweets para usuario ID: {user_id[0]}")
        task = asyncio.create_task(fetch_tweets_for_single_user(user_id[0], fetching_event))
        tasks.append(task)

        await asyncio.sleep(0.1)

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        print("⏹️ Tareas canceladas por solicitud de detención.")

    print("✅ Búsqueda de tweets completada.")


async def fetch_random_tasks_for_all_users(fetching_event):
    print("🎲 Iniciando tareas aleatorias para cada usuario (etapa 1)...")

    query = "SELECT id FROM users"
    users = run_query(query, fetchall=True)

    if not users:
        print("⚠ No hay usuarios en la base de datos.")
        return
    
    users = [u for u in users if u and isinstance(u, (list, tuple)) and len(u) > 0 and u[0] is not None]

    tasks = []
    for user in users:
        if fetching_event.is_set():
            print("⏹️ Proceso detenido por solicitud de usuario.")
            return

        user_id = user[0]
        print(f"👤 Iniciando tareas aleatorias para usuario ID: {user_id}")
        task = asyncio.create_task(fetch_random_tasks_for_user(user_id, fetching_event))
        tasks.append(task)
        await asyncio.sleep(0.1)

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        print("⏹️ Tareas canceladas por solicitud de detención.")

    print("✅ Tareas aleatorias completadas para todos los usuarios.")


async def fetch_random_tasks_for_user(user_id, fetching_event):
    if fetching_event.is_set():
        print(f"⏹️ Proceso detenido para usuario ID: {user_id}")
        return

    print(f"🎯 Ejecutando acciones aleatorias para usuario ID: {user_id}...")

    session_token = run_query(f"SELECT session FROM users WHERE id = '{user_id}'", fetchone=True)
    if not session_token:
        print(f"❌ No se encontró session para user ID {user_id}")
        return

    like_users = run_query(f"SELECT twitter_username FROM like_users WHERE user_id = '{user_id}'", fetchall=True)
    comment_users = run_query(f"SELECT twitter_username FROM comment_users WHERE user_id = '{user_id}'", fetchall=True)
    retweet_users = run_query(f"SELECT twitter_username FROM retweet_users WHERE user_id = '{user_id}'", fetchall=True)
    language = run_query(f"SELECT language FROM users WHERE id = '{user_id}'", fetchone=True)
    follow_targets = run_query(f"SELECT twitter_username FROM follow_users WHERE user_id = '{user_id}'", fetchall=True)

    async with aiohttp.ClientSession() as session:
        await run_random_actions(session, user_id, [u[0] for u in like_users], "like", get_like_limit_per_hour(user_id), session_token[0], fetching_event)
        await run_random_actions(session, user_id, [u[0] for u in retweet_users], "retweet", get_retweet_limit_per_hour(user_id), session_token[0], fetching_event)
        await run_random_actions(session, user_id, [u[0] for u in comment_users], "reply", get_comment_limit_per_hour(user_id), session_token[0], fetching_event, language)
        await run_random_actions(session, user_id, [u[0] for u in follow_targets], "follow", get_follow_limit_per_hour(user_id), session_token[0], fetching_event)

    print(f"✅ Acciones aleatorias finalizadas para usuario ID: {user_id}")


async def run_random_actions(session, user_id, usernames, action_type, limit, session_token, fetching_event, language=None):
    try:
        if not usernames:
            print(f"⚠️ Sin usuarios configurados para acción {action_type} en user ID {user_id}")
            return

        rapidkey = get_rapidapi_key()

        print(f"🎯 Ejecutando '{action_type}' para user ID {user_id}... (límite: {limit})")
        since_timestamp = int(time.time()) - 4 * 60 * 60
        count = 0
        
        if action_type == "follow":
            check_follows_last_hour = run_query(
                f"""
                SELECT COUNT(*) FROM random_actions
                WHERE user_id = '{user_id}' AND action_type = 'follow'
                AND created_at >= NOW() - INTERVAL '1 hour'
                """,
                fetchone=True
            )
            count = check_follows_last_hour[0] if check_follows_last_hour else 0

            if count >= limit:
                print(f"⛔ Usuario {user_id} ya alcanzó el límite de follows ({limit}) en la última hora.")
                return

            min_followers = 100

            for target_username in usernames:
                if fetching_event.is_set():
                    return

                url = f"https://twttrapi.p.rapidapi.com/user-followers?username={target_username}&count=20"
                headers_followers = {
                    'x-rapidapi-key': rapidkey,
                    'x-rapidapi-host': "twttrapi.p.rapidapi.com"
                }

                try:
                    async with session.get(url, headers=headers_followers) as resp:
                        if resp.status != 200:
                            print(f"❌ Error al obtener followers de @{target_username} ({resp.status})")
                            log_usage("RAPIDAPI")
                            continue

                        data = await resp.json()
                        followers = []
                        instructions = data.get("data", {}).get("user", {}).get("timeline_response", {}).get("timeline", {}).get("instructions", [])

                        for instruction in instructions:
                            if instruction.get("__typename") == "TimelineAddEntries":
                                for entry in instruction.get("entries", []):
                                    try:
                                        user_result = entry["content"]["content"]["userResult"]["result"]
                                        followers.append(user_result)
                                    except KeyError:
                                        continue
                        
                        log_usage("RAPIDAPI", count=len(followers))
                        
                        for user in followers:
                            if fetching_event.is_set():
                                return

                            if count >= limit:
                                print(f"✅ Límite alcanzado ({limit}) para acción 'follow'")
                                return

                            legacy = user.get("legacy", {})
                            verified = user.get("is_blue_verified", False)
                            followers_count = legacy.get("followers_count", 0)
                            username_to_follow = legacy.get("screen_name") or user.get("screen_name")
                            print(f'{username_to_follow} {followers_count} {verified}')
                            if not username_to_follow or not verified or followers_count < min_followers:
                                continue

                            already_followed = run_query(
                                f"SELECT 1 FROM random_actions WHERE twitter_id = '{username_to_follow}' AND action_type = 'follow'",
                                fetchone=True
                            )
                            if already_followed:
                                continue

                            url_follow = "https://twttrapi.p.rapidapi.com/follow-user"
                            payload = f"username={username_to_follow}"
                            headers_follow = {
                                'x-rapidapi-key': rapidkey,
                                'x-rapidapi-host': "twttrapi.p.rapidapi.com",
                                'Content-Type': "application/x-www-form-urlencoded",
                                'twttr-session': session_token
                            }

                            try:
                                async with session.post(url_follow, data=payload, headers=headers_follow) as follow_resp:
                                    log_usage("RAPIDAPI")
                                    if follow_resp.status == 200:
                                        print(f"✅ Seguido @{username_to_follow} ({followers_count} seguidores)")
                                        run_query(f"""
                                            INSERT INTO random_actions (user_id, twitter_id, action_type, created_at)
                                            VALUES ('{user_id}', '{username_to_follow}', 'follow', NOW())
                                        """)
                                        count += 1
                                    else:
                                        print(f"❌ Error al seguir @{username_to_follow} ({follow_resp.status})")
                            except Exception as e:
                                print(f"❌ Excepción al seguir a @{username_to_follow}: {e}")

                            await asyncio.sleep(0.2)

                except Exception as e:
                    print(f"❌ Error general al obtener followers de @{target_username}: {e}")

            return

        for username in usernames:
            if fetching_event.is_set():
                print(f"⏹️ Proceso detenido en acción '{action_type}' para user ID {user_id}")
                return

            if count >= limit:
                print(f"✅ Límite alcanzado ({limit}) para acción '{action_type}'")
                return
            

            query = f"from:{username} since_time:{since_timestamp}"
            params = {"query": query, "search_type": "Latest"}
            headers_rapid = {
                "x-rapidapi-key": rapidkey,
                "x-rapidapi-host": "twitter-api45.p.rapidapi.com",
            }
            search_url = "https://twitter-api45.p.rapidapi.com/search.php"

            async with session.get(search_url, headers=headers_rapid, params=params) as response:
                if response.status != 200:
                    print(f"❌ Error al buscar tweets para {username} ({response.status})")
                    log_usage("RAPIDAPI", count=1) 
                    continue

                try:
                    data = await response.json()
                    tweets = data.get("timeline", [])
                    log_usage("RAPIDAPI", count=len(tweets))
                    if not tweets:
                        print(f"⚠️ No se encontraron tweets para {username}")
                        continue
                except Exception as e:
                    print(f"❌ Error parseando respuesta de RapidApi Search: {e}")
                    log_usage("RAPIDAPI", count=1) 
                    continue

                for tweet in tweets[:10]:
                    if fetching_event.is_set():
                        print(f"⏹️ Proceso detenido mientras se procesaban acciones.")
                        return

                    if count >= limit:
                        print(f"✅ Límite alcanzado ({limit}) para acción '{action_type}'")
                        return

                    tweet_id = tweet.get("tweet_id")
                    tweet_text = tweet.get("text", "")

                    check_query = f"SELECT 1 FROM random_actions WHERE twitter_id = '{tweet_id}'"
                    already_done = run_query(check_query, fetchone=True)
                    if already_done:
                        print(f"⏭️ Acción ya realizada anteriormente sobre tweet {tweet_id[:8]}... Buscando otro.")
                        continue

                    headers_rapid = {
                        'x-rapidapi-key': rapidkey,
                        'x-rapidapi-host': "twttrapi.p.rapidapi.com",
                        'Content-Type': "application/x-www-form-urlencoded",
                        'twttr-session': session_token
                    }

                    if action_type == "like":
                        url = "https://twttrapi.p.rapidapi.com/favorite-tweet"
                        payload = f"tweet_id={tweet_id}"

                    elif action_type == "retweet":
                        url = "https://twttrapi.p.rapidapi.com/retweet-tweet"
                        payload = f"tweet_id={tweet_id}"

                    elif action_type == "reply":
                        if not language:
                            print(f"⚠️ Idioma no definido para user ID {user_id}, se omite reply.")
                            continue

                        generated_comment = generate_reply_with_openai(tweet_text, language)
                        if not generated_comment:
                            print(f"⚠️ No se pudo generar comentario para tweet {tweet_id}")
                            continue

                        url = "https://twttrapi.p.rapidapi.com/create-tweet"
                        payload = f"tweet_text={generated_comment}&in_reply_to_tweet_id={tweet_id}"

                    else:
                        print(f"❌ Acción desconocida: {action_type}")
                        continue

                    try:
                        async with session.post(url, data=payload, headers=headers_rapid) as resp:
                            log_usage("RAPIDAPI")
                            if resp.status == 200:
                                print(f"✅ Acción '{action_type}' realizada sobre tweet {tweet_id[:8]}... {tweet_text[:30]}")
                                count += 1
                                insert_query = f"""
                                    INSERT INTO random_actions (user_id, twitter_id, action_type, created_at)
                                    VALUES ('{user_id}', '{tweet_id}', '{action_type}', NOW())
                                """
                                run_query(insert_query)
                            else:
                                print(f"❌ Error al hacer {action_type} ({resp.status})")
                    except Exception as e:
                        print(f"❌ Excepción en acción {action_type}: {e}")

                    await asyncio.sleep(0.1)

        print(f"🎯 Finalizado '{action_type}' con {count}/{limit} acciones")
    except Exception as e:
        print(f"❌ Error {e}") 

def auto_post_tweet():
    user_id = 1 
    tweet_text = "¡Este es un tweet de prueba!"

    response, status_code = post_tweet(user_id, tweet_text)

    if status_code == 200:
        print("✅ Tweet automático publicado exitosamente.")
    else:
        print(f"❌ Error al publicar el tweet automático: {response.get('error')}")


async def post_tweets_for_all_users(posting_event):
    print("🚀 Iniciando publicación de tweets para cada usuario registrado...")

    query = "SELECT DISTINCT id FROM users"
    users = run_query(query, fetchall=True)
    print(users)

    if not users:
        print("⚠ No hay usuarios registrados en la base de datos.")
        return
    
    users = [u for u in users if u and isinstance(u, (list, tuple)) and len(u) > 0 and u[0] is not None]

    tasks = []
    for user_id in users:
        if posting_event.is_set():
            print("⏹️ Proceso detenido por solicitud de usuario.")
            return

        print(f"📢 Iniciando publicación de tweets para usuario ID: {user_id[0]}")
        task = asyncio.create_task(post_tweets_for_single_user(user_id[0], posting_event))
        tasks.append(task)

        await asyncio.sleep(0.1)

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        print("⏹️ Tareas de publicación canceladas por solicitud de detención.")

    print("✅ Publicación de tweets completada.")


async def post_tweets_for_single_user(user_id, posting_event):
    print(f"📢 Iniciando publicación de tweets para usuario ID: {user_id}...")

    if posting_event.is_set():
        print(f"⏹️ Proceso detenido para usuario ID: {user_id}.")
        return

    # Límites
    MAX_DAILY_POSTS = 100
    MAX_WINDOW_POSTS = 10  # 6-hour window

    # Guardrail horario actual
    tweet_limit_hour = await get_tweet_limit_per_hour(user_id)
    tweets_posted_last_hour = await count_tweets_for_user(user_id)
    if tweets_posted_last_hour >= tweet_limit_hour:
        print(f"⛔ Usuario {user_id} alcanzó el límite de {tweet_limit_hour} tweets por hora. Saltando publicación.")
        return

    # Conteo diario
    posted_today_row = run_query(
        f"""
        SELECT COUNT(*) FROM posted_tweets
        WHERE user_id = '{user_id}'
          AND created_at >= date_trunc('day', NOW())
        """,
        fetchone=True,
    )
    posted_today = posted_today_row[0] if posted_today_row else 0
    if posted_today >= MAX_DAILY_POSTS:
        print(f"⛔ Usuario {user_id} alcanzó el límite diario de {MAX_DAILY_POSTS}.")
        return

    # Conteo franja actual (0-6, 6-12, 12-18, 18-24)
    posted_in_window_row = run_query(
        f"""
        SELECT COUNT(*) FROM posted_tweets
        WHERE user_id = '{user_id}'
          AND created_at >= (date_trunc('day', NOW()) + (floor(extract(hour from NOW())/6) * interval '6 hours'))
          AND created_at <  (date_trunc('day', NOW()) + (floor(extract(hour from NOW())/6) * interval '6 hours') + interval '6 hours')
        """,
        fetchone=True,
    )
    posted_in_window = posted_in_window_row[0] if posted_in_window_row else 0
    if posted_in_window >= MAX_WINDOW_POSTS:
        print(f"⛔ Usuario {user_id} alcanzó el tope de {MAX_WINDOW_POSTS} en la franja actual.")
        return

    # Cargar candidatos (no todos) y publicar solo 1 para distribuir
    query_tweets = f"""
        SELECT tweet_id, tweet_text
        FROM collected_tweets
        WHERE user_id = '{user_id}' AND priority = 1
        LIMIT 50
    """
    tweets_to_post = run_query(query_tweets, fetchall=True) or []
    if not tweets_to_post:
        print(f"⚠ Usuario {user_id} no tiene tweets pendientes de publicación.")
        return

    # Calcular espaciado dentro de la franja restante
    now_utc = datetime.now(timezone.utc)
    current_bucket = now_utc.hour // 6
    window_start = now_utc.replace(hour=current_bucket * 6, minute=0, second=0, microsecond=0)
    window_end = window_start + timedelta(hours=6)

    remaining_today = MAX_DAILY_POSTS - posted_today
    remaining_window = min(MAX_WINDOW_POSTS - posted_in_window, remaining_today)
    if remaining_window <= 0:
        print(f"⛔ Usuario {user_id} sin cupo disponible en esta franja.")
        return

    last_post_row = run_query(
        f"""
        SELECT MAX(created_at)
        FROM posted_tweets
        WHERE user_id = '{user_id}'
          AND created_at >= (date_trunc('day', NOW()) + (floor(extract(hour from NOW())/6) * interval '6 hours'))
        """,
        fetchone=True,
    )
    last_post_dt = last_post_row[0] if last_post_row and last_post_row[0] else None

    seconds_remaining = max(1.0, (window_end - now_utc).total_seconds())
    ideal_spacing = max(30.0, seconds_remaining / float(max(1, remaining_window)))
    jitter = random.uniform(0.6, 1.4)

    if last_post_dt is not None:
        if last_post_dt.tzinfo is None:
            last_post_dt = last_post_dt.replace(tzinfo=timezone.utc)
        elapsed = (now_utc - last_post_dt).total_seconds()
        if elapsed < ideal_spacing * jitter:
            print(f"⏳ Espaciando publicaciones para user {user_id}: elapsed={elapsed:.0f}s < target={(ideal_spacing * jitter):.0f}s")
            return

    # Elegir 1 tweet al azar de los primeros 50
    tweet_id, tweet_text = random.choice(tweets_to_post)

    media_rows = run_query(
        f"""
        SELECT file_url FROM collected_media
        WHERE user_id = '{user_id}' AND tweet_id = '{tweet_id}'
        """,
        fetchall=True,
    )
    media_urls = [row[0] for row in media_rows] if media_rows else []

    extraction_filter = get_extraction_filter(user_id)
    if extraction_filter in ["cb2", "cb3", "cb4"] and "https://" not in tweet_text:
        print(f"❌ No se publicó el tweet por falta de media/link para filtros cb2/cb3/cb4.")
        return

    response, status_code = post_tweet(user_id, tweet_text, media_urls=media_urls)
    if status_code == 200:
        insert_query = f"INSERT INTO posted_tweets (user_id, tweet_text, created_at) VALUES ('{user_id}', '{tweet_text}', NOW())"
        run_query(insert_query)

        print(f"✅ Tweet publicado y guardado en posted_tweets: {tweet_text[:50]}...")

        delete_query = f"DELETE FROM collected_tweets WHERE tweet_id = '{tweet_id}' AND user_id = '{user_id}'"
        run_query(delete_query)
        delete_query2 = f"DELETE FROM collected_media WHERE tweet_id = '{tweet_id}' AND user_id = '{user_id}'"
        run_query(delete_query2)

        print(f"🗑️ Tweet eliminado de collected_tweets después de ser publicado: {tweet_text[:50]}...")
    else:
        print(f"❌ No se pudo publicar el tweet: {response.get('error')}")

    await asyncio.sleep(random.uniform(0.2, 0.8))

    print(f"✅ Publicación de tweets completada para usuario ID: {user_id}.")
    
    # LOGGING POST STATS
    try:
        username_row = run_query(f"SELECT username FROM users WHERE id = {user_id}", fetchone=True)
        username = username_row[0] if username_row else f"User {user_id}"
        
        from services.db_service import log_api_operation
        if status_code == 200:
            log_api_operation(user_id, username, "POST", "SUCCESS", 0, 1, 0, 0, "TwitterAPI", None)
            log_event(user_id, "POSTED", f"{username} posted 1 posts at {datetime.now().strftime('%H:%M')}")
        else:
            log_api_operation(user_id, username, "POST", "FAILED", 0, 0, 1, 0, "TwitterAPI", str(response.get('error')))
    except Exception as log_err:
        print(f"⚠️ Error logging post stats: {log_err}")


async def post_tweets_for_user(session, user_id, tweets, posting_event, tweet_limit, tweets_posted_last_hour):
    try:
        if posting_event.is_set():
            print(f"⏹️ Proceso detenido para usuario ID: {user_id}.")
            return

        print(f"📢 Publicando tweets para usuario ID: {user_id}...")

        for tweet_id, tweet_text in tweets:
            if posting_event.is_set():
                print(f"⏹️ Proceso detenido mientras se publicaban tweets.")
                break

            if tweets_posted_last_hour >= tweet_limit:
                print(f"⛔ Usuario {user_id} alcanzó el límite mientras publicaba. Deteniendo la publicación.")
                break

            check_query = f"SELECT 1 FROM posted_tweets WHERE user_id = '{user_id}' AND tweet_text = '{tweet_text}' LIMIT 1"
            exists = run_query(check_query, fetchone=True)
            
            if exists:
                print(f"⚠ El tweet ya fue publicado previamente. Saltando: {tweet_text[:50]}...")
                continue

            response, status_code = post_tweet(user_id, tweet_text)

            if status_code == 200:
                insert_query = f"INSERT INTO posted_tweets (user_id, tweet_text, created_at) VALUES ('{user_id}', '{tweet_text}', NOW())"
                run_query(insert_query)
                print(f"✅ Tweet guardado en posted_tweets: {tweet_text[:50]}...")
                
                delete_query = f"DELETE FROM collected_tweets WHERE tweet_id = '{tweet_id}' AND user_id = '{user_id}'"
                run_query(delete_query)
                print(f"🗑️ Tweet eliminado de collected_tweets después de ser publicado: {tweet_text[:50]}...")
                
                tweets_posted_last_hour += 1 
            else:
                print(f"❌ No se pudo publicar el tweet: {response.get('error')}")

            await asyncio.sleep(2)  

    except asyncio.CancelledError:
        print(f"⏹️ Publicación de tweets cancelada para usuario ID: {user_id}.")

    print(f"✅ Publicación de tweets finalizada para usuario ID: {user_id}.")


# async def start_tweet_fetcher():
#     print('🚀 Iniciando el servicio de recolección de tweets...')
#     while True:
#         await fetch_tweets_for_all_users()
    
#         print("⏳ Esperando 5 minutos antes de la próxima búsqueda...")
#         await asyncio.sleep(300)  



# OLD 


''' async def extract_by_combination(session, user_id, monitored_users, keywords, limit, fetching_event):
    since_timestamp = int(time.time()) - 4 * 60 * 60
    collected_count = 0

    socialdata_api_key = get_socialdata_api_key()
    if not socialdata_api_key:
        print("❌ No se pudo obtener la API Key de SocialData.")
        return 0

    headers = {"Authorization": f"Bearer {socialdata_api_key}"}
    combinaciones = list(itertools.product(monitored_users, keywords))

    for username, keyword in combinaciones:
        if fetching_event.is_set():
            print(f"⏹️ Proceso detenido mientras recorría combinaciones.")
            return collected_count

        if collected_count >= limit:
            return collected_count

        base = f"from:{username} ({keyword}) since_time:{since_timestamp}"
        extraction_filter = get_extraction_filter(user_id)

        query = f"({base})"
        if extraction_filter == "cb2":
            query = f"({base} filter:images)"
        elif extraction_filter == "cb3":
            query = f"({base} filter:native_video)"
        elif extraction_filter == "cb4":
            query = f"({base} filter:media)"
        elif extraction_filter == "cb5":
            query = f"({base} filter:images -filter:videos)"
        elif extraction_filter == "cb6":
            query = f"({base} -filter:images -filter:videos -filter:links)"

        params = {"query": query, "type": "Latest"}
        print(f"🔎 Consultando: {query}")

        async with session.get(SOCIALDATA_API_URL, headers=headers, params=params) as response:
            if response.status != 200:
                print(f"❌ Error al buscar tweets ({response.status}) para: {query}")
                log_usage("SOCIALDATA", count=1)
                continue

            try:
                data = await response.json()
            except Exception as e:
                print(f"❌ Error parseando respuesta para {query}: {e}")
                log_usage("SOCIALDATA", count=1)
                continue

            tweets = data.get("tweets", [])
            log_usage("SOCIALDATA", count=len(tweets))
            if not tweets:
                continue

            for tweet in tweets:
                if fetching_event.is_set() or collected_count >= limit:
                    return collected_count

                tweet_id = tweet["id_str"]
                tweet_text = tweet["full_text"]
                created_at = tweet["tweet_created_at"]
                
                # if extraction_filter in ["cb2", "cb3", "cb4"] and "https://" not in tweet_text:
                #     continue 

                save_collected_tweet(user_id, "combined", None, tweet_id, tweet_text, created_at, extraction_filter)
                collected_count += 1
                await asyncio.sleep(0.1)

    return collected_count

    
async def extract_by_copy_user(session, user_id, monitored_users, limit, fetching_event):
    since_timestamp = int(time.time()) - 4 * 60 * 60
    collected_count = 0

    socialdata_api_key = get_socialdata_api_key()
    if not socialdata_api_key:
        print("❌ No se pudo obtener la API Key de SocialData.")
        return 0

    headers = {"Authorization": f"Bearer {socialdata_api_key}"}
    extraction_filter = get_extraction_filter(user_id)

    for username in monitored_users:
        if fetching_event.is_set():
            print(f"⏹️ Proceso detenido mientras recorría usuarios.")
            return collected_count

        if collected_count >= limit:
            print(f"✅ Límite alcanzado: {collected_count}/{limit}")
            return collected_count

        base = f"from:{username} since_time:{since_timestamp}"

        if extraction_filter == "cb2":
            query = f"({base} filter:images)"
        elif extraction_filter == "cb3":
            query = f"({base} filter:native_video)"
        elif extraction_filter == "cb4":
            query = f"({base} filter:media)"
        elif extraction_filter == "cb5":
            query = f"({base} filter:images -filter:videos)"
        elif extraction_filter == "cb6":
            query = f"({base} -filter:images -filter:videos -filter:links)"
        else:
            query = f"({base})" 

        params = {"query": query, "type": "Latest"}
        print(f"🔎 Consultando: {query}")

        async with session.get(SOCIALDATA_API_URL, headers=headers, params=params) as response:
            if response.status != 200:
                print(f"❌ Error al buscar tweets ({response.status}) para @{username}")
                log_usage("SOCIALDATA", count=1)
                continue

            try:
                data = await response.json()
            except Exception as e:
                print(f"❌ Error parseando respuesta para @{username}: {e}")
                continue

            tweets = data.get("tweets", [])
            log_usage("SOCIALDATA", count=len(tweets))
            if not tweets:
                print(f"⚠️ No se encontraron tweets para @{username}")
                continue

            for tweet in tweets:
                if fetching_event.is_set() or collected_count >= limit:
                    return collected_count

                tweet_id = tweet["id_str"]
                tweet_text = tweet["full_text"]
                created_at = tweet["tweet_created_at"]

                # if extraction_filter in ["cb2", "cb3", "cb4"] and "https://" not in tweet_text:
                #     continue 

                save_collected_tweet(user_id, "full_account_copy", username, tweet_id, tweet_text, created_at, extraction_filter)
                collected_count += 1
                print(f"💾 Tweet guardado de @{username}: {tweet_id}")
                await asyncio.sleep(0.1)

    print(f"🎯 Extracción completa. Total tweets: {collected_count}/{limit}")
    return collected_count
'''


async def old_fetch_tweets_for_monitored_users_with_keywords(session, user_id, monitored_users, keywords, limit, fetching_event):
    since_timestamp = int(time.time()) - 4 * 60 * 60
    collected_count = 0

    try:
        if fetching_event.is_set():
            print(f"⏹️ Proceso detenido para usuario ID: {user_id}.")
            return

        print(f"🔍 Buscando tweets para usuario ID: {user_id} con cada keyword por usuario (una sola vez)...")

        socialdata_api_key = get_socialdata_api_key()
        if not socialdata_api_key:
            print("❌ No se pudo obtener la API Key de SocialData.")
            return

        headers = {"Authorization": f"Bearer {socialdata_api_key}"}

        combinaciones = list(itertools.product(monitored_users, keywords))

        print(f"🔢 Total de combinaciones a consultar: {len(combinaciones)}")

        for username, keyword in combinaciones:
            if fetching_event.is_set():
                print(f"⏹️ Proceso detenido mientras recorría combinaciones.")
                return

            if collected_count >= limit:
                print(f"✅ Límite de {limit} tweets alcanzado.")
                return

            query = f"(from:{username} ({keyword}) filter:media since_time:{since_timestamp})"
            params = {"query": query, "type": "Latest"}

            print(f"🔎 Consultando: {query}")

            async with session.get(SOCIALDATA_API_URL, headers=headers, params=params) as response:
                if response.status != 200:
                    print(f"❌ Error al buscar tweets ({response.status}) para: {query}")
                    continue

                try:
                    data = await response.json()
                except Exception as e:
                    print(f"❌ Error parseando respuesta para {query}: {e}")
                    continue

                tweets = data.get("tweets", [])

                if not tweets:
                    print(f"⚠️ No se encontraron tweets para {username} con keyword '{keyword}'.")
                    continue

                for tweet in tweets:
                    if fetching_event.is_set():
                        print(f"⏹️ Proceso detenido mientras se procesaban tweets.")
                        return

                    if collected_count >= limit:
                        print(f"✅ Límite de {limit} tweets alcanzado.")
                        return

                    tweet_id = tweet["id_str"]
                    tweet_text = tweet["full_text"]
                    created_at = tweet["tweet_created_at"]

                    print(f"✅ Nuevo tweet encontrado: {tweet_text[:50]}...")
                    save_collected_tweet(user_id, "combined", None, tweet_id, tweet_text, created_at)
                    print(f"💾 Tweet guardado en la base de datos: {tweet_id}")
                    collected_count += 1

                    await asyncio.sleep(0.1)

        print(f"🎯 Finalizado. Total tweets: {collected_count}/{limit}")

    except asyncio.CancelledError:
        print(f"⏹️ Tarea cancelada para usuario ID: {user_id}.")
        raise 
    except Exception as e:
        log_event(user_id, "ERROR", f"Error obteniendo tweets: {str(e)}")
        print(f"❌ Error al buscar tweets: {e}")


async def old_fetch_tweets_for_single_user(user_id, fetching_event):
    print(f"🔍 Iniciando búsqueda de tweets para usuario ID: {user_id}...")

    if fetching_event.is_set():
        print(f"⏹️ Proceso detenido para usuario ID: {user_id}.")
        return

    query_users = f"SELECT DISTINCT twitter_username FROM monitored_users WHERE user_id = '{user_id}'"
    monitored_users = run_query(query_users, fetchall=True) or []

    query_keywords = f"SELECT DISTINCT keyword FROM user_keywords WHERE user_id = '{user_id}'"
    monitored_keywords = run_query(query_keywords, fetchall=True) or []

    if not monitored_users or not monitored_keywords:
        print(f"⚠ Usuario {user_id} no tiene usuarios o palabras clave monitoreadas.")
        return

    limit_ph = await get_tweet_limit_per_hour(user_id)
    limit = round(limit_ph * 1.3)
    
    async with aiohttp.ClientSession() as session:
        await old_fetch_tweets_for_monitored_users_with_keywords(
            session,
            user_id,
            [user[0] for user in monitored_users],
            [keyword[0] for keyword in monitored_keywords],
            limit,
            fetching_event
        )

    print(f"✅ Búsqueda de tweets completada para usuario ID: {user_id}.")


async def old_fetch_tweets_for_all_users(fetching_event):
    print("🔍 Buscando tweets para cada usuario registrado (etapa 1)...")

    query = "SELECT DISTINCT id FROM users"
    users = run_query(query, fetchall=True)
    print(users)

    if not users:
        print("⚠ No hay usuarios registrados en la base de datos.")
        return

    tasks = []
    for user_id in users:
        if fetching_event.is_set():
            print("⏹️ Proceso detenido por solicitud de usuario.")
            return

        print(f"👤 Iniciando búsqueda de tweets para usuario ID: {user_id[0]}")
        task = asyncio.create_task(old_fetch_tweets_for_single_user(user_id[0], fetching_event))
        tasks.append(task)

        await asyncio.sleep(0.1)

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        print("⏹️ Tareas canceladas por solicitud de detención.")

    print("✅ Búsqueda de tweets completada.")


async def extract_from_drive_link(user_id, folder_id, drive_link):
    drive_service = get_drive_service()
    collected_count = 0
    language = run_query(f"SELECT language FROM users WHERE id = '{user_id}'", fetchone=True)

    results = drive_service.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        fields="files(id, name, mimeType, webViewLink)"
    ).execute()
    files = results.get("files", [])

    grouped = {}
    for file in files:
        base_name = extract_base_name(file["name"])
        grouped.setdefault(base_name, []).append(file)

    for base_name, media_group in grouped.items():
        check_query = (
            f"SELECT 1 FROM drive_media_processed "
            f"WHERE user_id = {user_id} AND base_name = '{base_name}' AND drive_link = '{drive_link}'"
        )
        exists = run_query(check_query, fetchone=True)

        if exists:
            print(f"⏭️ Ya procesado: {base_name}")
            continue

        prompt = f"Write a tweet based on the following topic: {base_name.replace('_', ' ')}"
        tweet_text = generate_post_with_openai(prompt, language)
        # tweet_text = 'Just look at that beautiful sky! Makes you want to get out there and enjoy the day.'

        tweet_id = f"drive-{base_name}"
        save_collected_tweet_simple(user_id, "drive", None, tweet_id, tweet_text, datetime.now(timezone.utc))

        for file in media_group:
            file_name = file['name'].replace("'", "''")
            file_url = file['webViewLink'].replace("'", "''")

            insert_media = (
                f"INSERT INTO collected_media (tweet_id, user_id, file_name, file_url) "
                f"VALUES ('{tweet_id}', {user_id}, '{file_name}', '{file_url}')"
            )
            run_query(insert_media)

        insert_processed = (
            f"INSERT INTO drive_media_processed (user_id, drive_link, base_name, created_at) "
            f"VALUES ({user_id}, '{drive_link}', '{base_name}', NOW())"
        )
        run_query(insert_processed)

        print(f"💾 Procesado y guardado: {base_name}")
        collected_count += 1

    return collected_count



# JSON
