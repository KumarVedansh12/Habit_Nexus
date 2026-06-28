import os
import re
import secrets
from urllib.parse import urlparse


def load_local_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return

    with open(env_path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value


load_local_env()

try:
    import psycopg2
    from psycopg2 import pool
    from psycopg2.extras import RealDictCursor
except ModuleNotFoundError as exc:
    raise RuntimeError(
        "psycopg2-binary is not installed for the Python you are using. "
        "Install it with `python -m pip install psycopg2-binary` or install "
        "all project dependencies with `python -m pip install -r requirements.txt`."
    ) from exc


DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
POSTGRES_POOL = None

TABLE_NAMES = (
    "users",
    "routines",
    "task_logs",
    "friend_requests",
    "activities",
    "friends",
    "notifications",
    "notification_dismissals",
    "dsa_profiles",
    "dsa_topics",
    "pending_topics",
    "dsa_history",
    "challenges",
    "landing_content",
    "landing_contact",
    "developer_notifications",
    "suggestions",
)

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS users(
        id SERIAL PRIMARY KEY,
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
        leetcode TEXT,
        is_developer INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        created_at TEXT,
        last_login_at TEXT,
        public_id TEXT UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS routines(
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        task_name TEXT NOT NULL,
        completed INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS task_logs(
        id SERIAL PRIMARY KEY,
        routine_id INTEGER,
        log_date TEXT,
        completed INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS friend_requests(
        id SERIAL PRIMARY KEY,
        sender_id INTEGER,
        receiver_id INTEGER,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP::TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS activities (
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        activity TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP::TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS friends(
        id SERIAL PRIMARY KEY,
        user1_id INTEGER,
        user2_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP::TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notifications(
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        message TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP::TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notification_dismissals(
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        notification_key TEXT NOT NULL,
        dismissed_at TEXT DEFAULT CURRENT_TIMESTAMP::TEXT,
        UNIQUE(user_id, notification_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dsa_profiles(
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        leetcode_username TEXT,
        cached_data TEXT,
        last_sync TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dsa_topics(
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        topic_name TEXT,
        completed INTEGER DEFAULT 0,
        target INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pending_topics(
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        topic_name TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dsa_history(
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        solved_count INTEGER,
        log_date TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS challenges (
        id SERIAL PRIMARY KEY,
        challenger_id INTEGER NOT NULL,
        challenged_id INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        winner_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP::TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS landing_content (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        link_label TEXT,
        link_url TEXT,
        is_published INTEGER DEFAULT 1,
        display_order INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP::TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP::TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS suggestions (
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        name TEXT NOT NULL,
        email TEXT,
        message TEXT NOT NULL,
        status TEXT DEFAULT 'new',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP::TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS landing_contact (
        id SERIAL PRIMARY KEY,
        contact_key TEXT UNIQUE NOT NULL,
        contact_value TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP::TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS developer_notifications (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        is_pinned INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP::TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP::TEXT
    )
    """,
)


class PostgresCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()


class PostgresConnection:
    def __init__(self, connection, connection_pool=None):
        self.connection = connection
        self.connection_pool = connection_pool
        self.closed = False

    def execute(self, sql, params=None):
        cursor = self.connection.cursor(cursor_factory=RealDictCursor)
        if params is None:
            cursor.execute(sql)
        else:
            cursor.execute(sql, params)
        return PostgresCursor(cursor)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.connection_pool:
            try:
                self.connection.rollback()
            except Exception:
                self.connection_pool.putconn(self.connection, close=True)
                return
            self.connection_pool.putconn(self.connection)
        else:
            self.connection.close()


def get_db_connection():
    global POSTGRES_POOL

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required. HabitNexus is PostgreSQL-only.")

    parsed = urlparse(DATABASE_URL)
    if not parsed.scheme.startswith("postgres"):
        raise RuntimeError("DATABASE_URL must be a PostgreSQL connection string.")

    if POSTGRES_POOL is None:
        POSTGRES_POOL = pool.ThreadedConnectionPool(
            minconn=int(os.environ.get("DB_POOL_MIN", "1")),
            maxconn=int(os.environ.get("DB_POOL_MAX", "5")),
            dsn=DATABASE_URL,
            connect_timeout=int(os.environ.get("DB_CONNECT_TIMEOUT", "5")),
            sslmode=os.environ.get("DATABASE_SSLMODE", "require"),
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5,
        )

    connection = POSTGRES_POOL.getconn()
    return PostgresConnection(connection, POSTGRES_POOL)


def public_id_seed(username):
    seed = re.sub(r"[^a-z0-9]+", "_", username.strip().lower())
    seed = seed.strip("_") or "student"
    return seed[:18]


def generate_public_id(existing_public_ids, username):
    seed = public_id_seed(username)
    public_id = None
    while not public_id or public_id in existing_public_ids:
        public_id = f"{seed}_{secrets.randbelow(9000) + 1000}"
    existing_public_ids.add(public_id)
    return public_id


def get_table_columns(conn, table_name):
    rows = conn.execute(
        """
        SELECT column_name AS name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
        """,
        (table_name,)
    ).fetchall()
    return {row["name"] for row in rows}


def init_db():
    conn = get_db_connection()

    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)

    user_columns = get_table_columns(conn, "users")
    user_migrations = {
        "is_developer": "INTEGER DEFAULT 0",
        "is_active": "INTEGER DEFAULT 1",
        "created_at": "TEXT",
        "last_login_at": "TEXT",
        "public_id": "TEXT",
    }
    for column, definition in user_migrations.items():
        if column not in user_columns:
            conn.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")

    friends_columns = get_table_columns(conn, "friends")
    if "created_at" not in friends_columns:
        conn.execute(
            "ALTER TABLE friends ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP::TEXT"
        )

    conn.execute(
        "UPDATE users SET created_at=COALESCE(created_at::TEXT, CURRENT_TIMESTAMP::TEXT)"
    )

    existing_public_ids = {
        row["public_id"]
        for row in conn.execute(
            """
            SELECT public_id FROM users
            WHERE public_id IS NOT NULL
            AND public_id!=''
            AND public_id NOT LIKE 'HN-%'
            """
        ).fetchall()
    }
    users_needing_public_id = conn.execute(
        """
        SELECT id, username
        FROM users
        WHERE public_id IS NULL OR public_id='' OR public_id LIKE 'HN-%'
        """
    ).fetchall()
    for user in users_needing_public_id:
        public_id = generate_public_id(existing_public_ids, user["username"])
        conn.execute(
            "UPDATE users SET public_id=%s WHERE id=%s",
            (public_id, user["id"])
        )

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_public_id ON users(public_id)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_landing_contact_key ON landing_contact(contact_key)"
    )
    conn.execute(
        """
        DELETE FROM notification_dismissals older
        USING notification_dismissals newer
        WHERE older.user_id=newer.user_id
        AND older.notification_key=newer.notification_key
        AND older.id<newer.id
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_dismissals_user_key
        ON notification_dismissals(user_id, notification_key)
        """
    )

    conn.commit()
    conn.close()
