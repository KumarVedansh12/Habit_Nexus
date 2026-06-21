import sqlite3

def get_db_connection():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():

    conn = get_db_connection()

    # USERS

    conn.execute("""
    CREATE TABLE IF NOT EXISTS users(

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        username TEXT UNIQUE NOT NULL,

        email TEXT UNIQUE NOT NULL,

        password TEXT NOT NULL,
                
        profile_image TEXT,

        college TEXT,

        branch TEXT,

        year TEXT,

        bio TEXT,

        github TEXT,

        linkedin TEXT,

        leetcode TEXT

    )
    """)

    # ROUTINES

    conn.execute("""
    CREATE TABLE IF NOT EXISTS routines(

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id INTEGER NOT NULL,

        task_name TEXT NOT NULL,

        completed INTEGER DEFAULT 0
    )
    """)

    # TASK LOGS

    conn.execute("""
    CREATE TABLE IF NOT EXISTS task_logs(

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        routine_id INTEGER,

        log_date TEXT,

        completed INTEGER DEFAULT 0
    )
    """)

    # FRIEND REQUESTS

    conn.execute("""
    CREATE TABLE IF NOT EXISTS friend_requests(

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        sender_id INTEGER,

        receiver_id INTEGER,

        status TEXT DEFAULT 'pending',
                 
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    #Activity_feed

    conn.execute("""

    CREATE TABLE IF NOT EXISTS activities (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id INTEGER,

        activity TEXT,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )

    """)


    # FRIENDS

    conn.execute("""
    CREATE TABLE IF NOT EXISTS friends(

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user1_id INTEGER,

        user2_id INTEGER,
                
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # NOTIFICATIONS

    conn.execute("""
    CREATE TABLE IF NOT EXISTS notifications(

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id INTEGER,

        message TEXT,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    # DSA PROFILE

    conn.execute("""
    CREATE TABLE IF NOT EXISTS dsa_profiles(

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id INTEGER,

        leetcode_username TEXT,

        cached_data TEXT,

        last_sync TEXT
    )
    """)


    # DSA TOPICS

    conn.execute("""
    CREATE TABLE IF NOT EXISTS dsa_topics(

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id INTEGER,

        topic_name TEXT,

        completed INTEGER DEFAULT 0,

        target INTEGER DEFAULT 0
    )
    """)

    # PENDING TOPICS

    conn.execute("""
    CREATE TABLE IF NOT EXISTS pending_topics(

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id INTEGER,

        topic_name TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS dsa_history(

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id INTEGER,

        solved_count INTEGER,

        log_date TEXT
    )
    """)
    # CHALLENGES TABLE

    conn.execute("""
    CREATE TABLE IF NOT EXISTS challenges (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        challenger_id INTEGER NOT NULL,

        challenged_id INTEGER NOT NULL,

        status TEXT DEFAULT 'pending',

        winner_id INTEGER,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

    )
    """)



    conn.commit()

    conn.close()

