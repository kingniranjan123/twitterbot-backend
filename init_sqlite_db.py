import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'nexus.db')

def init_db():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create tables
    tables = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            twitter_id TEXT NOT NULL,
            username TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            language TEXT DEFAULT 'English',
            custom_style TEXT,
            password TEXT,
            session TEXT,
            rate_limit INTEGER DEFAULT 10,
            followers INTEGER DEFAULT 0,
            following INTEGER DEFAULT 0,
            status TEXT DEFAULT '-',
            extraction_filter TEXT DEFAULT 'cb1',
            profile_pic TEXT,
            notes TEXT,
            account_status TEXT DEFAULT 'ACTIVE',
            session_cookie TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS collected_tweets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            tweet_id TEXT NOT NULL,
            tweet_text TEXT NOT NULL,
            image_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            priority INTEGER DEFAULT 0
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS collected_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            tweet_id TEXT NOT NULL,
            file_url TEXT NOT NULL,
            media_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS posted_tweets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            tweet_id TEXT,
            tweet_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            event_type TEXT NOT NULL,
            event_description TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            key TEXT,
            service TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS monitored_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            twitter_username TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS user_keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            keyword TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS random_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            twitter_id TEXT,
            user_id INTEGER,
            action_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requests INTEGER,
            api TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS global_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL,
            value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    ]

    for table_sql in tables:
        try:
            cursor.execute(table_sql)
        except Exception as e:
            print(f"Error creating table: {e}")
            print(table_sql)

    # Insert default API keys if not present
    cursor.execute("SELECT COUNT(*) FROM api_keys WHERE id = 1")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO api_keys (id, name, key, service) VALUES (1, 'OpenAI', 'YOUR_OPENAI_KEY', 'openai')")
        cursor.execute("INSERT INTO api_keys (id, name, key, service) VALUES (5, 'TwitterAPI', '6f60bb14a3ff43d59daf70cf2857d1c3', 'twitterapi')")
        cursor.execute("INSERT INTO api_keys (id, name, key, service) VALUES (3, 'SocialData', 'YOUR_SOCIALDATA_KEY', 'socialdata')")

    conn.commit()
    conn.close()
    print(f"Database initialized successfully at {db_path}")

if __name__ == "__main__":
    init_db()
