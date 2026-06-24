# HabitNexus

HabitNexus is a Flask-based productivity and peer-accountability platform built for engineering students. It combines daily routine tracking, DSA preparation, LeetCode progress, analytics, friends, challenges, leaderboards, notifications, and a protected developer console in one workspace.

The project started as a personal/resume project and is being upgraded toward a production-ready student platform.

## Key Features

- Student authentication with username, email, or public Student ID login.
- Password reset using registered email and Student ID.
- Unique public Student ID format such as `username_0000`.
- Daily routine tracking saved by date, including previous-day history.
- Calendar view for historical routine progress.
- Analytics dashboard for habit completion, consistency, DSA growth, and recent activity.
- DSA tracker with topic targets, pending topics, CSV export, and LeetCode sync.
- Friends hub with privacy-aware user search by Student ID.
- Friend requests, friend profiles, challenges, and weekly leaderboard.
- Public profile preview for unconnected users with limited profile-only data.
- Full profile view for connected friends.
- Notification center with account notifications, AI coach reminders, and developer pinned notices.
- Protected developer console for user management, growth metrics, landing-page content, contact details, suggestions, and pinned notifications.
- Public landing page with prototype showcase metrics, developer-managed updates, contact details, and suggestion form.
- PostgreSQL support for production with SQLite fallback for local development.

## AI Feature

HabitNexus currently uses an in-app AI-style study coach notification system. It does not require an external AI provider or API key.

The AI coach:

- Looks at today's pending routines.
- Generates a focused reminder with a motivational quote.
- Shows the notification on the dashboard and notification center.
- Allows each user to dismiss the generated AI notification for that day.
- Stores dismissed generated notifications in `notification_dismissals`.

Developer pinned notifications are different from AI coach notifications. They are created and managed only from the developer console and cannot be removed by normal users.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Backend | Python, Flask |
| Templates | Jinja2 |
| Frontend | HTML, CSS, JavaScript |
| Charts | ApexCharts |
| Database | SQLite for local development, PostgreSQL for production |
| Auth | Flask sessions, Werkzeug password hashing |
| HTTP client | Requests |
| Production server | Gunicorn |

## Project Structure

```text
HabitNexus/
├── app.py
├── database.py
├── requirements.txt
├── Procfile
├── PRODUCTION.md
├── .env.example
├── scripts/
│   └── migrate_sqlite_to_postgres.py
├── static/
│   ├── css/
│   │   ├── account.css
│   │   ├── analytics.css
│   │   ├── calendar.css
│   │   ├── dashboard.css
│   │   ├── developer.css
│   │   ├── dsa.css
│   │   ├── friends.css
│   │   ├── landing.css
│   │   ├── leaderboard.css
│   │   ├── readability.css
│   │   └── style.css
│   ├── images/
│   │   └── default-avatar.svg
│   ├── js/
│   │   ├── charts.js
│   │   ├── csrf.js
│   │   ├── profile.js
│   │   ├── sidebar.js
│   │   └── theme.js
│   └── uploads/
│       └── profile_pictures/
└── templates/
    ├── auth/
    │   ├── forgot_password.html
    │   ├── login.html
    │   └── register.html
    ├── dashboard/
    │   ├── analytics.html
    │   ├── calendar.html
    │   ├── dashboard.html
    │   ├── dsa_tracker.html
    │   └── notifications.html
    ├── developer/
    │   └── dashboard.html
    ├── friends/
    │   ├── challenge_room.html
    │   ├── friend_profile.html
    │   ├── friends_hub.html
    │   ├── leaderboard.html
    │   ├── profile_preview.html
    │   └── profile_view.html
    ├── guide/
    │   └── guide.html
    ├── layout/
    │   ├── base.html
    │   ├── footer.html
    │   ├── navbar.html
    │   └── sidebar.html
    ├── profile/
    │   ├── profile.html
    │   └── settings.html
    └── home.html
```

## Local Setup

1. Clone the repository.

```bash
git clone <your-repository-url>
cd HabitNexus
```

2. Create and activate a virtual environment.

```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install dependencies.

```bash
pip install -r requirements.txt
```

4. Run the app locally.

```bash
python3 app.py
```

By default, local development uses SQLite through `database.db`.

## Environment Variables

Create a `.env` file or configure these variables on your hosting platform.

```bash
APP_ENV=production
SECRET_KEY=change-this-to-a-long-random-secret
DATABASE_URL=postgresql://habitnexus_user:password@host:5432/habitnexus
DATABASE_SSLMODE=require
SESSION_COOKIE_SECURE=1
DEVELOPER_EMAILS=your-admin-email@example.com
DB_POOL_MIN=1
DB_POOL_MAX=5
DB_CONNECT_TIMEOUT=5
```

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | Set to `production` in production environments. |
| `SECRET_KEY` | Required in production for secure Flask sessions. |
| `DATABASE_URL` | PostgreSQL connection string. If omitted, SQLite is used. |
| `DATABASE_SSLMODE` | PostgreSQL SSL mode, commonly `require` on hosted databases. |
| `SESSION_COOKIE_SECURE` | Set to `1` when the app runs behind HTTPS. |
| `DEVELOPER_EMAILS` | Comma-separated admin emails that should always regain developer access. |
| `DB_POOL_MIN` | Minimum PostgreSQL pooled connections per Gunicorn worker. |
| `DB_POOL_MAX` | Maximum PostgreSQL pooled connections per Gunicorn worker. |
| `DB_CONNECT_TIMEOUT` | PostgreSQL connection timeout in seconds. |
| `SQLITE_DATABASE` | Optional local SQLite database path. Defaults to `database.db`. |

## Production and PostgreSQL

HabitNexus uses PostgreSQL when `DATABASE_URL` is set. Without `DATABASE_URL`, it falls back to SQLite for local development.

Initialize PostgreSQL tables:

```bash
DATABASE_URL="postgresql://user:password@host:5432/database" python3 -c "from database import init_db; init_db()"
```

Migrate existing SQLite data to PostgreSQL:

```bash
DATABASE_URL="postgresql://user:password@host:5432/database" python3 scripts/migrate_sqlite_to_postgres.py --sqlite database.db --replace
```

Run with Gunicorn:

```bash
gunicorn app:app --workers 2 --threads 4 --timeout 120 --access-logfile -
```

The included `Procfile` is intended for platforms such as Render.

## Render Deployment Checklist

- Add a PostgreSQL database on Render.
- Set `DATABASE_URL` from the Render PostgreSQL connection string.
- Set `APP_ENV=production`.
- Set a strong `SECRET_KEY`.
- Set `DATABASE_SSLMODE=require`.
- Set `SESSION_COOKIE_SECURE=1`.
- Set `DEVELOPER_EMAILS` to your admin account email so developer access can recover after migration.
- Keep `DB_POOL_MAX` modest for Supabase, for example `5`, to avoid exhausting database connections.
- Use `pip install -r requirements.txt` as the build command.
- Use `gunicorn app:app --workers 2 --threads 4 --timeout 120 --access-logfile -` as the start command.
- Do not rely on `database.db` in production.
- Run `init_db()` once during setup or migration. The app no longer runs heavy schema initialization during web worker startup.

## Database Tables

| Table | Purpose |
| --- | --- |
| `users` | Student accounts, profile data, developer flag, public Student ID. |
| `routines` | User-created daily routines. |
| `task_logs` | Date-based routine completion history. |
| `friend_requests` | Pending and accepted friend request workflow. |
| `friends` | Connected user relationships. |
| `activities` | Recent activity feed data. |
| `notifications` | User account notifications. |
| `notification_dismissals` | Per-user dismissed generated AI notifications. |
| `dsa_profiles` | Saved LeetCode username and cached profile data. |
| `dsa_topics` | DSA roadmap topics with completion targets. |
| `pending_topics` | DSA backlog items. |
| `dsa_history` | Daily LeetCode solved-count history. |
| `challenges` | Friend challenge state and winners. |
| `landing_content` | Developer-managed landing-page updates. |
| `landing_contact` | Developer-managed contact details. |
| `developer_notifications` | Developer-managed pinned notifications. |
| `suggestions` | Landing-page user suggestions for the developer. |

## Routes and API Details

HabitNexus is primarily a server-rendered Flask app. Routes return HTML pages, redirects, CSV exports, or simple POST responses.

### Public and Auth Routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/` | Public landing page. |
| `GET, POST` | `/register` | Create account. |
| `GET, POST` | `/login` | Login with username, email, or Student ID. |
| `POST` | `/logout` | Logout. |
| `GET, POST` | `/forgot-password` | Reset password using email and Student ID. |
| `POST` | `/suggestions` | Submit public suggestion to developer. |

### Dashboard and Routine Routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/dashboard` | Student dashboard with daily routine overview. |
| `GET` | `/guide` | User guide for learning how to use HabitNexus. |
| `POST` | `/add_routine` | Add a routine. |
| `POST` | `/toggle/<id>` | Toggle routine completion for selected date. |
| `POST` | `/delete/<id>` | Delete a routine. |
| `GET` | `/calendar` | Calendar progress view. |
| `GET` | `/calendar_day/<date>` | View one day of routine data. |
| `GET` | `/analytics` | Analytics dashboard. |
| `GET` | `/export_habits` | Export habit data as CSV. |

### DSA Routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/dsa_tracker` | DSA tracker page. |
| `POST` | `/save_leetcode` | Save and verify LeetCode username. |
| `POST` | `/add_dsa_topic` | Add DSA topic. |
| `POST` | `/update_dsa_topic/<id>` | Update DSA topic progress. |
| `POST` | `/delete_dsa_topic/<id>` | Delete DSA topic. |
| `POST` | `/add_pending_topic` | Add pending DSA topic. |
| `POST` | `/delete_pending_topic/<id>` | Delete pending topic. |
| `GET` | `/export_dsa` | Export DSA data as CSV. |

### Friends, Profiles, and Challenge Routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/friends-hub` | Friends hub and user discovery/search. |
| `GET, POST` | `/search-users` | Search users by public Student ID. |
| `POST` | `/send-request/<user_id>` | Send friend request. |
| `POST` | `/accept-request/<request_id>` | Accept friend request. |
| `POST` | `/reject-request/<request_id>` | Reject friend request. |
| `POST` | `/remove-friend/<friend_id>` | Remove friend. |
| `GET` | `/profile/<user_id>` | View another user's profile with privacy rules. |
| `GET` | `/friend-profile/<user_id>` | Friend profile view. |
| `GET, POST` | `/challenge/<friend_id>` | Create or view a challenge with a friend. |
| `GET` | `/leaderboard` | Weekly leaderboard. |

### Notification Routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/notifications` | Notification center. |
| `POST` | `/notifications/clear` | Clear account notifications. |
| `POST` | `/notifications/<notification_id>/delete` | Delete one account notification. |
| `POST` | `/notifications/ai-dismiss` | Dismiss generated AI coach notification for the current user. |

### Profile and Settings Routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET, POST` | `/profile` | Manage current user's profile. |
| `GET, POST` | `/settings` | Manage account settings, send suggestions, password, data deletion, and account deletion. |

### Developer Routes

Developer routes require a logged-in user with `is_developer=1`.

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/developer` | Developer dashboard. |
| `POST` | `/developer/users/<user_id>/toggle` | Activate/deactivate non-developer users. |
| `POST` | `/developer/content` | Add landing-page update. |
| `POST` | `/developer/content/<content_id>/update` | Update landing-page content. |
| `POST` | `/developer/content/<content_id>/toggle` | Publish/hide landing-page content. |
| `POST` | `/developer/contact` | Update public contact details. |
| `POST` | `/developer/notifications/add` | Publish pinned notification. |
| `POST` | `/developer/notifications/<notification_id>/update` | Update pinned notification. |
| `POST` | `/developer/notifications/<notification_id>/toggle` | Pin or unpin developer notification. |
| `POST` | `/developer/notifications/<notification_id>/delete` | Delete developer notification. |
| `POST` | `/developer/suggestions/<suggestion_id>/status` | Mark suggestion as new, reviewed, or resolved. |
| `POST` | `/developer/suggestions/<suggestion_id>/delete` | Remove a resolved suggestion. |

## Privacy Model

- Users are searched by public Student ID instead of listing every user publicly.
- Before connection, another student can only see limited profile information such as name, college, and bio.
- DSA details, personal links, and deeper progress data are reserved for connected friends.
- Developer users are visible as official platform accounts.
- Developer pinned notifications are managed only by the developer console.

## Security Notes

- Passwords are hashed with Werkzeug.
- CSRF tokens are required for POST forms.
- Flask session cookies are configured as HTTP-only.
- Production mode requires `SECRET_KEY`.
- Profile uploads are limited by extension, MIME type, and size.
- Developer routes are protected by an `is_developer` account flag.
- Normal users cannot deactivate developer accounts.

## External Integrations

### LeetCode GraphQL

HabitNexus syncs public LeetCode profile data using LeetCode's GraphQL endpoint:

```text
https://leetcode.com/graphql
```

This is used to verify usernames and store daily solved-count history.

### ApexCharts

The frontend uses ApexCharts for dashboard, analytics, leaderboard, and developer-console charts.

## Useful Commands

Run locally:

```bash
python3 app.py
```

Run production server locally:

```bash
gunicorn app:app --workers 2 --threads 4 --timeout 120 --access-logfile -
```

Check Python syntax:

```bash
python3 -m py_compile app.py database.py
```

Initialize database:

```bash
python3 -c "from database import init_db; init_db()"
```

Migrate SQLite to PostgreSQL:

```bash
DATABASE_URL="postgresql://user:password@host:5432/database" python3 scripts/migrate_sqlite_to_postgres.py --sqlite database.db --replace
```

## Current Roadmap Ideas

- Add email-based password reset tokens instead of Student ID based local reset.
- Add stronger admin audit logs for developer actions.
- Add automated tests for authentication, privacy rules, and friend workflows.
- Add API-style JSON endpoints if a mobile app or SPA frontend is planned.
- Add background jobs for scheduled notifications and LeetCode sync.
- Add rate limiting for login, password reset, and user search.

## License

Add your preferred license before publishing publicly.
