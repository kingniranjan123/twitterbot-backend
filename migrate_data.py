import sqlite3
import os
import re

db_path = os.path.join(os.path.dirname(__file__), 'nexus.db')
backup_path = os.path.join(os.path.dirname(__file__), 'backup.sql')

def migrate_data():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    with open(backup_path, 'r', encoding='utf-8') as f:
        in_copy_block = False
        current_table = None
        current_columns = []
        
        # Keep track of tables we've created to avoid recreating
        created_tables = set()

        for line in f:
            if line.startswith('COPY public.'):
                # Example: COPY public.users (id, twitter_id, username) FROM stdin;
                match = re.match(r'COPY public\.([a-zA-Z0-9_]+) \((.*?)\) FROM stdin;', line)
                if match:
                    current_table = match.group(1)
                    # We skip some internal postgrest/supabase tables if any
                    if current_table in ['schema_migrations', 'spatial_ref_sys']:
                        continue
                        
                    current_columns = [col.strip().strip('"') for col in match.group(2).split(',')]
                    in_copy_block = True
                    
                    # Create table if it doesn't exist
                    # For simplicity, id is INTEGER PRIMARY KEY, everything else is TEXT
                    if current_table not in created_tables:
                        cols_def = []
                        for col in current_columns:
                            if col == 'id':
                                cols_def.append("id INTEGER PRIMARY KEY")
                            else:
                                cols_def.append(f'"{col}" TEXT')
                        
                        create_stmt = f"CREATE TABLE IF NOT EXISTS {current_table} ({', '.join(cols_def)});"
                        
                        try:
                            # If table exists but missing columns, this might fail, so we'll try to add missing columns
                            cursor.execute(create_stmt)
                            
                            # Check if existing table is missing any columns and add them
                            cursor.execute(f"PRAGMA table_info({current_table})")
                            existing_cols = [row[1] for row in cursor.fetchall()]
                            
                            for col in current_columns:
                                if col not in existing_cols:
                                    cursor.execute(f"ALTER TABLE {current_table} ADD COLUMN \"{col}\" TEXT")
                                    
                        except Exception as e:
                            print(f"Error creating/altering table {current_table}: {e}")
                            
                        created_tables.add(current_table)
                continue
                
            if in_copy_block:
                if line.strip() == '\\.':
                    in_copy_block = False
                    current_table = None
                    conn.commit()
                    continue
                
                # It's a data row. Tab separated.
                # Remove trailing newline but NOT trailing tabs
                row_data = line.rstrip('\n').split('\t')
                
                # Replace \N with None
                row_data = [None if val == '\\N' else val for val in row_data]
                
                # Handle special case where a row might have fewer columns than header due to malformed data
                if len(row_data) < len(current_columns):
                    row_data.extend([None] * (len(current_columns) - len(row_data)))
                elif len(row_data) > len(current_columns):
                    row_data = row_data[:len(current_columns)]
                
                placeholders = ', '.join(['?'] * len(current_columns))
                insert_stmt = f"INSERT OR IGNORE INTO {current_table} ({', '.join(['\"'+c+'\"' for c in current_columns])}) VALUES ({placeholders})"
                
                try:
                    cursor.execute(insert_stmt, row_data)
                except Exception as e:
                    print(f"Error inserting into {current_table}: {e}")
                    # print(f"Data: {row_data}")

    conn.commit()
    conn.close()
    print("Migration completed!")

if __name__ == '__main__':
    migrate_data()
