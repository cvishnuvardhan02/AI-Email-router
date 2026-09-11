import sqlite3
from datetime import datetime

DB_NAME = "analytics.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Dropping the old table to add the new columns below.
    c.execute("DROP TABLE IF EXISTS email_logs")
    c.execute('''CREATE TABLE email_logs
                 (thread_id TEXT PRIMARY KEY,
                  message_id TEXT,
                  folder_id TEXT,
                  sender TEXT,
                  assigned_name TEXT,
                  assigned_rep TEXT,
                  received_time DATETIME,
                  read_time DATETIME,
                  replied_time DATETIME,
                  response_minutes REAL,
                  summary TEXT,
                  meeting_requested TEXT,
                  meeting_details TEXT,
                  notification_sent INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

def log_incoming_email(thread_id, message_id, sender, assigned_name, assigned_rep, received_time_ms,
                        folder_id=None, summary="", meeting_requested="", meeting_details="",
                        notification_sent=0):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Convert Zoho's millisecond timestamp to standard datetime
    dt = datetime.fromtimestamp(int(received_time_ms)/1000.0)
    c.execute('''INSERT OR IGNORE INTO email_logs
                 (thread_id, message_id, folder_id, sender, assigned_name, assigned_rep,
                  received_time, summary, meeting_requested, meeting_details, notification_sent)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (thread_id, message_id, folder_id, sender, assigned_name, assigned_rep, dt,
               summary, meeting_requested, meeting_details, notification_sent))
    conn.commit()
    conn.close()

def get_pending_threads():
    """Fetches all emails that haven't been replied to yet, along with the folder_id
    needed to poll their live read-status."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT thread_id, message_id, folder_id, received_time
                 FROM email_logs
                 WHERE replied_time IS NULL''')
    rows = c.fetchall()
    conn.close()
    return rows

def update_read_time(thread_id):
    """Marks the email as Read by the sales rep."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT read_time FROM email_logs WHERE thread_id=?", (thread_id,))
    row = c.fetchone()
    if row and not row[0]: # Only update if it is currently blank
        c.execute("UPDATE email_logs SET read_time=? WHERE thread_id=?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), thread_id))
    conn.commit()
    conn.close()

def update_reply_time(thread_id, reply_time_ms):
    """Marks the email as Replied and calculates response time."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT received_time FROM email_logs WHERE thread_id=?", (thread_id,))
    row = c.fetchone()
    if row:
        received_time = datetime.fromisoformat(row[0])
        replied_time = datetime.fromtimestamp(int(reply_time_ms)/1000.0)
        diff_minutes = (replied_time - received_time).total_seconds() / 60.0

        c.execute('''UPDATE email_logs
                     SET replied_time=?, response_minutes=?
                     WHERE thread_id=?''',
                  (replied_time.strftime("%Y-%m-%d %H:%M:%S"), diff_minutes, thread_id))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database rebuilt: summary/meeting/notification columns added, spam tracking removed!")
