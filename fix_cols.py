import sqlite3
conn = sqlite3.connect('nexus.db')
c = conn.cursor()
try:
    c.execute("ALTER TABLE users ADD COLUMN post_window_morning TEXT DEFAULT '09:00-12:00'")
    print('Added morning')
except Exception as e: print(e)
try:
    c.execute("ALTER TABLE users ADD COLUMN post_window_evening TEXT DEFAULT '18:00-22:00'")
    print('Added evening')
except Exception as e: print(e)
conn.commit()
conn.close()
