import psycopg2
import os

def process_tally_sync_data():
    # Connect to your PostgreSQL database using your environment configurations
    conn = psycopg2.urlopen(os.getenv("DATABASE_URL")) # or direct parameters
    cursor = conn.cursor()
    
    try:
        cursor.execute("UPDATE sync_metadata SET last_synced = NOW() WHERE source = 'Tally';")
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    
    return {"status": "completed"}