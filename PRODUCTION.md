# HabitNexus Production Setup

## PostgreSQL

HabitNexus uses PostgreSQL when `DATABASE_URL` is set. Without `DATABASE_URL`, it falls back to local SQLite for development.

Required environment variables:

```bash
APP_ENV=production
SECRET_KEY=your-long-random-secret
DATABASE_URL=postgresql://user:password@host:5432/database
DATABASE_SSLMODE=require
SESSION_COOKIE_SECURE=1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Initialize PostgreSQL tables:

```bash
DATABASE_URL="postgresql://user:password@host:5432/database" python3 -c "from database import init_db; init_db()"
```

Migrate existing SQLite data:

```bash
DATABASE_URL="postgresql://user:password@host:5432/database" python3 scripts/migrate_sqlite_to_postgres.py --sqlite database.db --replace
```

`--replace` clears PostgreSQL tables first. Omit it only when importing into a new empty database.

## Run

```bash
gunicorn app:app
```

For hosted platforms, keep `database.db` out of production and use the managed PostgreSQL connection string as `DATABASE_URL`.
