import sys
sys.path.append('.')
from app import app
from services.db_service import run_query

with app.app_context():
    print('Adding account_status')
    run_query("ALTER TABLE users ADD COLUMN IF NOT EXISTS account_status VARCHAR(20) DEFAULT 'active';")
    print('Adding consecutive_failures')
    run_query("ALTER TABLE users ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER DEFAULT 0;")
    print('Adding ai_enabled')
    run_query("ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_enabled BOOLEAN DEFAULT FALSE;")
    print('Done')
