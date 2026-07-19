import pg8000.native as pg
from config import Config

def fix_db():
    try:
        print("Connecting to DB...")
        db = pg.Connection(
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            host=Config.DB_HOST,
            port=int(Config.DB_PORT),
            database=Config.DB_NAME
        )
        print("Connected! Creating table...")
        db.run("""
            CREATE TABLE IF NOT EXISTS daily_schedule (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                scheduled_date DATE NOT NULL,
                scheduled_times TEXT
            )
        """)
        print("Table daily_schedule created successfully!")
        db.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fix_db()
