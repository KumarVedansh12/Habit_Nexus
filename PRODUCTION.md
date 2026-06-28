# HabitNexus Production Setup

## PostgreSQL

HabitNexus is PostgreSQL-only. `DATABASE_URL` is required in every environment.

Required environment variables:

```bash
APP_ENV=production
SECRET_KEY=your-long-random-secret
DATABASE_URL=postgresql://user:password@host:5432/database
DATABASE_SSLMODE=require
SESSION_COOKIE_SECURE=1
DEVELOPER_EMAILS=your-admin-email@example.com
DB_POOL_MIN=1
DB_POOL_MAX=5
DB_CONNECT_TIMEOUT=5
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Initialize PostgreSQL tables:

```bash
DATABASE_URL="postgresql://user:password@host:5432/database" python3 -c "from database import init_db; init_db()"
```

## Run

```bash
gunicorn app:app --workers 2 --threads 4 --timeout 120 --access-logfile -
```

For hosted platforms, use the managed PostgreSQL connection string as `DATABASE_URL`.

`init_db()` is intentionally not called during app startup. Run it once during setup or migration, then start Gunicorn. This keeps hosted workers fast and prevents every web worker from running schema checks on boot.

If developer access is lost after migration, set `DEVELOPER_EMAILS` to the email address of your admin account. After that account logs in, HabitNexus will restore `is_developer=1` automatically.
