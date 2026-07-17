import pg8000.native as pg
from flask import g
from config import Config
from openai import OpenAI
from datetime import datetime, timedelta


def get_openai_api_key():
    query = "SELECT key FROM api_keys WHERE id = 1"
    result = run_query(query, fetchone=True)
    return result[0] if result else None  


def get_db():
    if 'db' not in g:
        g.db = pg.Connection(
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            host=Config.DB_HOST,
            port=int(Config.DB_PORT),
            database=Config.DB_NAME
        )
        
        # Ensure openai_configs table exists
        try:
            g.db.run("""
                CREATE TABLE IF NOT EXISTS openai_configs (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT,
                    prompt_type TEXT,
                    prompt_text TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
        except Exception as e:
            print(f"Error ensuring openai_configs table: {e}")

        # Ensure api_health_log table exists
        try:
            g.db.run("""
                CREATE TABLE IF NOT EXISTS api_health_log (
                    id SERIAL PRIMARY KEY,
                    api_name VARCHAR(100) NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    latency_ms INTEGER,
                    credits_remaining INTEGER,
                    error_message TEXT,
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        except Exception as e:
            print(f"Error ensuring api_health_log table: {e}")

    return g.db


def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def run_query(query, params=None, fetchone=False, fetchall=False):
    db = get_db()
    
    if params is None:
        params = ()
        
    try:
        result = db.run(query, *params)

        if fetchone:
            return result[0] if result else None
        if fetchall:
            return result
        return None
    
    except Exception as e:
        print(f"❌ Error en consulta SQL: {str(e)}")
        return None


def log_event(user_id, event_type, description):
    val_user_id = f"'{user_id}'" if user_id and user_id != 'SYSTEM' else "NULL"
    
    # Escape single quotes in description
    safe_description = description.replace("'", "''")
    
    query = f"""
    INSERT INTO logs (user_id, event_type, event_description)
    VALUES ({val_user_id}, '{event_type}', '{safe_description}')
    """
    run_query(query)