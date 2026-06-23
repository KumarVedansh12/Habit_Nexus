from database import get_db_connection, init_db, using_postgres


init_db()
conn = get_db_connection()

print("Backend:", "PostgreSQL" if using_postgres() else "SQLite")
print("\nUSERS")
for row in conn.execute(
    """
    SELECT id, username, public_id, profile_image, is_developer, is_active
    FROM users
    ORDER BY id
    """
).fetchall():
    print(dict(row))

print("\nFRIEND REQUESTS")
for row in conn.execute("SELECT * FROM friend_requests ORDER BY id").fetchall():
    print(dict(row))

print("\nFRIENDS")
for row in conn.execute("SELECT * FROM friends ORDER BY id").fetchall():
    print(dict(row))

conn.close()
