from database import get_db_connection, init_db, using_postgres


init_db()
conn = get_db_connection()

conn.execute("DELETE FROM friend_requests")
conn.execute("DELETE FROM friends")

conn.commit()
conn.close()

print("Cleaned friend requests and friendships from", "PostgreSQL" if using_postgres() else "SQLite")
