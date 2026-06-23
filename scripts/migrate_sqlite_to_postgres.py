#!/usr/bin/env python3
"""
Copy HabitNexus data from SQLite to PostgreSQL.

Usage:
    DATABASE_URL=postgresql://user:pass@host:5432/dbname \
    python3 scripts/migrate_sqlite_to_postgres.py --sqlite database.db --replace
"""

import argparse
import os
import sqlite3
import sys

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import TABLE_NAMES, init_db  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="Migrate HabitNexus SQLite data to PostgreSQL.")
    parser.add_argument("--sqlite", default="database.db", help="Path to the SQLite database file.")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing PostgreSQL table data before importing SQLite rows.",
    )
    return parser.parse_args()


def sqlite_rows(sqlite_path, table_name):
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    try:
        rows = sqlite_conn.execute(f"SELECT * FROM {table_name} ORDER BY id").fetchall()
        return [dict(row) for row in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        sqlite_conn.close()


def insert_rows(pg_conn, table_name, rows):
    if not rows:
        return 0

    columns = list(rows[0].keys())
    column_sql = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    sql = f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})"

    with pg_conn.cursor() as cursor:
        for row in rows:
            cursor.execute(sql, [row[column] for column in columns])
    return len(rows)


def reset_sequence(pg_conn, table_name):
    with pg_conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT setval(
                pg_get_serial_sequence(%s, 'id'),
                COALESCE((SELECT MAX(id) FROM {table_name}), 1),
                (SELECT COUNT(*) FROM {table_name}) > 0
            )
            """,
            (table_name,)
        )


def main():
    args = parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required and must point to PostgreSQL.")
    if not os.path.exists(args.sqlite):
        raise SystemExit(f"SQLite database not found: {args.sqlite}")

    init_db()
    kwargs = {}
    if os.environ.get("DATABASE_SSLMODE"):
        kwargs["sslmode"] = os.environ["DATABASE_SSLMODE"]
    pg_conn = psycopg2.connect(database_url, **kwargs)
    try:
        if args.replace:
            with pg_conn.cursor() as cursor:
                cursor.execute(
                    "TRUNCATE TABLE " + ", ".join(TABLE_NAMES) + " RESTART IDENTITY CASCADE"
                )

        total = 0
        for table_name in TABLE_NAMES:
            rows = sqlite_rows(args.sqlite, table_name)
            copied = insert_rows(pg_conn, table_name, rows)
            reset_sequence(pg_conn, table_name)
            total += copied
            print(f"{table_name}: copied {copied} rows")

        pg_conn.commit()
        print(f"Migration complete. Copied {total} rows to PostgreSQL.")
    except Exception:
        pg_conn.rollback()
        raise
    finally:
        pg_conn.close()


if __name__ == "__main__":
    main()
