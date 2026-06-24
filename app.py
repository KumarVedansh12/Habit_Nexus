from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    Response,
    jsonify,
    url_for,
    flash,
    g,
    abort
)
import requests
import csv
import calendar as cal
import hmac
import re
import secrets
import base64
from functools import wraps
from io import StringIO
import json
from flask import Response
import io
from datetime import (
date,
timedelta,
datetime
)

from database import (
    get_db_connection
)
import os
from werkzeug.utils import secure_filename

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

import os

app = Flask(__name__)

configured_secret = os.environ.get("SECRET_KEY")
if os.environ.get("APP_ENV") == "production" and not configured_secret:
    raise RuntimeError("SECRET_KEY must be set in production")
app.secret_key = configured_secret or "dev-secret-change-before-production"

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    MAX_CONTENT_LENGTH=3 * 1024 * 1024
)

UPLOAD_FOLDER = "static/uploads/profile_pictures"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(
    app.config["UPLOAD_FOLDER"],
    exist_ok=True
)

ALLOWED_PROFILE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_PROFILE_MIMES = {"image/png", "image/jpeg", "image/webp"}
PROFILE_IMAGE_MIME_BY_TYPE = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


def detect_profile_image_type(uploaded_file):
    header = uploaded_file.stream.read(12)
    uploaded_file.stream.seek(0)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"
    return None


def profile_image_data_url(uploaded_file, detected_type):
    uploaded_file.stream.seek(0)
    data = uploaded_file.stream.read()
    uploaded_file.stream.seek(0)
    mime_type = PROFILE_IMAGE_MIME_BY_TYPE[detected_type]
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def default_avatar_url():
    return url_for("static", filename="images/default-avatar.svg")


def profile_image_url(user):
    if not user:
        return default_avatar_url()
    user_id = None
    for key in ("profile_user_id", "user_id", "sender_id", "id"):
        try:
            user_id = user[key]
        except (KeyError, IndexError, TypeError):
            user_id = getattr(user, key, None)
        if user_id:
            break
    if not user_id:
        return default_avatar_url()
    return url_for("profile_image", user_id=user_id)


def public_id_seed(username):
    seed = re.sub(r"[^a-z0-9]+", "_", username.strip().lower())
    seed = seed.strip("_") or "student"
    return seed[:18]


def generate_public_id(conn, username):
    seed = public_id_seed(username)
    while True:
        public_id = f"{seed}_{secrets.randbelow(9000) + 1000}"
        existing = conn.execute(
            "SELECT 1 FROM users WHERE public_id=?",
            (public_id,)
        ).fetchone()
        if not existing:
            return public_id


def delete_user_progress(conn, user_id):
    routine_ids = [
        row["id"]
        for row in conn.execute(
            "SELECT id FROM routines WHERE user_id=?",
            (user_id,)
        ).fetchall()
    ]
    if routine_ids:
        placeholders = ",".join("?" for _ in routine_ids)
        conn.execute(
            f"DELETE FROM task_logs WHERE routine_id IN ({placeholders})",
            routine_ids
        )

    for table in (
        "routines",
        "activities",
        "notifications",
        "notification_dismissals",
        "dsa_profiles",
        "dsa_topics",
        "pending_topics",
        "dsa_history",
    ):
        conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))

    conn.execute(
        """
        DELETE FROM challenges
        WHERE challenger_id=? OR challenged_id=? OR winner_id=?
        """,
        (user_id, user_id, user_id)
    )
    conn.execute(
        "DELETE FROM friend_requests WHERE sender_id=? OR receiver_id=?",
        (user_id, user_id)
    )
    conn.execute(
        "DELETE FROM friends WHERE user1_id=? OR user2_id=?",
        (user_id, user_id)
    )


def delete_user_account(conn, user_id):
    delete_user_progress(conn, user_id)
    conn.execute("UPDATE suggestions SET user_id=NULL WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))


def parse_iso_date(value, default=None):
    if not value:
        return default or date.today()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return default or date.today()


def redirect_dashboard_for(day):
    today = date.today()
    if day and day != today:
        return redirect(url_for("dashboard", date=day.isoformat()))
    return redirect(url_for("dashboard"))


def wants_json_response():
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    )


def get_dashboard_routine_state(conn, user_id, selected_day):
    day_key = selected_day.isoformat()
    routine_rows = conn.execute(
        """
        SELECT
            routines.id,
            routines.task_name,
            COALESCE(task_logs.completed, 0) AS completed
        FROM routines
        LEFT JOIN task_logs
            ON task_logs.routine_id=routines.id
            AND task_logs.log_date=?
        WHERE routines.user_id=?
        ORDER BY routines.id DESC
        """,
        (day_key, user_id)
    ).fetchall()
    routines = [
        {
            "id": int(routine["id"]),
            "task_name": routine["task_name"],
            "completed": int(routine["completed"] or 0),
        }
        for routine in routine_rows
    ]
    total = len(routines)
    completed = sum(routine["completed"] for routine in routines)
    progress = round((completed / total) * 100) if total else 0
    focus_task = next((routine for routine in routines if not routine["completed"]), None)
    return {
        "routines": routines,
        "total": total,
        "completed": completed,
        "pending": max(total - completed, 0),
        "progress": progress,
        "focus_task": focus_task,
    }


def dashboard_routine_json(conn, user_id, selected_day, message=None):
    state = get_dashboard_routine_state(conn, user_id, selected_day)
    state["selected_date"] = selected_day.isoformat()
    state["streak"] = calculate_streak_from_conn(conn, user_id)
    state["message"] = message
    return jsonify(state)


def normalize_activity_time(value):
    if not value:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def build_ai_notifications(pending_routines, selected_day, progress):
    if selected_day != date.today() or not pending_routines:
        return []

    quotes = [
        "Small progress is still progress.",
        "One focused action can change the whole day.",
        "Do the next visible thing, then let momentum help.",
        "Consistency is built by returning, not by being perfect.",
    ]
    pending_names = [routine["task_name"] for routine in pending_routines[:3]]
    joined_tasks = ", ".join(pending_names)
    quote = quotes[len(pending_routines) % len(quotes)]

    if progress == 0:
        title = "Start with one routine"
        message = f"{joined_tasks} is still waiting. {quote}"
    elif len(pending_routines) == 1:
        title = "One task left"
        message = f"Only {joined_tasks} is pending. Finish it cleanly. {quote}"
    else:
        title = f"{len(pending_routines)} routines pending"
        message = f"Focus on {pending_names[0]} first, then continue. {quote}"

    return [{
        "key": f"ai-routine-{selected_day.isoformat()}",
        "title": title,
        "message": message,
        "kind": "AI coach",
        "created_at": selected_day.isoformat(),
    }]


def get_dismissed_notification_keys(conn, user_id):
    rows = conn.execute(
        """
        SELECT notification_key
        FROM notification_dismissals
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchall()
    return {row["notification_key"] for row in rows}


PROTOTYPE_METRICS = {
    "students": 1200,
    "routines": 8400,
    "completions": 96,
    "dsa_solved": 75,
    "challenges": 40,
}

DEFAULT_CONTACT_DETAILS = {
    "email": "hello@habitnexus.dev",
    "phone": "+91 7052501218",
    "location": "Kanpur Nagar, Uttar Pradesh",
    "linkedin": "",
    "github": "",
}


def rows_to_contact_details(rows):
    details = DEFAULT_CONTACT_DETAILS.copy()
    for row in rows:
        details[row["contact_key"]] = row["contact_value"] or ""
    return details


def configured_developer_emails():
    raw_emails = os.environ.get("DEVELOPER_EMAILS", "")
    return {
        email.strip().lower()
        for email in raw_emails.split(",")
        if email.strip()
    }


def is_configured_developer(user):
    return bool(user and user["email"].lower() in configured_developer_emails())


def ensure_developer_access(conn, user):
    if not is_configured_developer(user):
        return user
    if int(user["is_developer"] or 0):
        return user

    conn.execute(
        "UPDATE users SET is_developer=1 WHERE id=?",
        (user["id"],)
    )
    conn.commit()
    promoted_user = dict(user)
    promoted_user["is_developer"] = 1
    return promoted_user


def session_user_context(user):
    profile_image = user["profile_image"]
    if profile_image and profile_image.startswith("data:"):
        profile_image = None
    return {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "profile_image": profile_image,
        "is_developer": int(user["is_developer"] or 0),
        "is_active": int(user["is_active"] or 0),
        "public_id": user["public_id"],
    }


def refresh_session_user(user):
    session["user_context"] = session_user_context(user)
    g.current_user = session["user_context"]


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


app.jinja_env.globals["csrf_token"] = csrf_token
app.jinja_env.globals["profile_image_url"] = profile_image_url


@app.route("/profile-image/<int:user_id>")
def profile_image(user_id):
    conn = get_db_connection()
    user = conn.execute(
        "SELECT profile_image FROM users WHERE id=?",
        (user_id,)
    ).fetchone()
    conn.close()

    image_value = user["profile_image"] if user else None
    if not image_value:
        return redirect(default_avatar_url())

    if image_value.startswith("data:"):
        match = re.fullmatch(r"data:(image/(?:png|jpeg|webp));base64,(.+)", image_value, re.DOTALL)
        if not match:
            return redirect(default_avatar_url())
        try:
            image_bytes = base64.b64decode(match.group(2), validate=True)
        except ValueError:
            return redirect(default_avatar_url())
        response = Response(image_bytes, mimetype=match.group(1))
        response.cache_control.private = True
        response.cache_control.no_cache = True
        response.cache_control.max_age = 0
        return response

    if image_value.startswith("/static/"):
        local_path = os.path.join(app.root_path, image_value.lstrip("/"))
        if os.path.exists(local_path):
            return redirect(image_value)
        return redirect(default_avatar_url())

    if image_value.startswith(("http://", "https://")):
        return redirect(image_value)

    return redirect(default_avatar_url())


@app.before_request
def load_current_user_and_protect_forms():
    g.current_user = None
    if request.endpoint == "static":
        return None

    user_id = session.get("user_id")
    if user_id:
        cached_user = session.get("user_context")
        if cached_user and cached_user.get("id") == user_id:
            g.current_user = cached_user
        else:
            conn = get_db_connection()
            g.current_user = conn.execute(
                """
                SELECT id, username, email, profile_image, is_developer, is_active, public_id
                FROM users
                WHERE id=?
                """,
                (user_id,)
            ).fetchone()
            if g.current_user and g.current_user["is_active"]:
                g.current_user = ensure_developer_access(conn, g.current_user)
                refresh_session_user(g.current_user)
            conn.close()
        if not g.current_user or not g.current_user["is_active"]:
            session.clear()
            g.current_user = None

    if request.method == "POST":
        expected = session.get("csrf_token", "")
        provided = request.form.get("_csrf_token", "") or request.headers.get("X-CSRF-Token", "")
        if not expected or not provided or not hmac.compare_digest(expected, provided):
            abort(400, description="Invalid or missing security token")


@app.context_processor
def inject_account_context():
    return {"current_user": g.get("current_user")}


@app.errorhandler(413)
def profile_upload_too_large(error):
    flash("Profile images must be smaller than 3 MB.", "error")
    return redirect(url_for("profile"))
@app.route("/")
def home():
    conn = get_db_connection()
    landing_updates = conn.execute(
        """
        SELECT * FROM landing_content
        WHERE is_published=1
        ORDER BY display_order, id DESC
        """
    ).fetchall()
    contact_rows = conn.execute(
        "SELECT contact_key, contact_value FROM landing_contact"
    ).fetchall()
    conn.close()
    return render_template(
        "home.html",
        metrics=PROTOTYPE_METRICS,
        landing_updates=landing_updates,
        contact_details=rows_to_contact_details(contact_rows),
        current_year=date.today().year
    )


@app.route("/suggestions", methods=["POST"])
def submit_suggestion():
    name = request.form.get("name", "").strip()[:80]
    email = request.form.get("email", "").strip().lower()[:150]
    message = request.form.get("message", "").strip()[:1200]
    if not name or len(message) < 10:
        flash("Please include your name and a suggestion of at least 10 characters.", "error")
        return redirect(url_for("home", _anchor="suggestions"))
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        flash("Enter a valid email address or leave it blank.", "error")
        return redirect(url_for("home", _anchor="suggestions"))

    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO suggestions (user_id, name, email, message)
        VALUES (?, ?, ?, ?)
        """,
        (session.get("user_id"), name, email or None, message)
    )
    conn.commit()
    conn.close()
    flash("Thank you. Your suggestion was sent to the developer.", "success")
    return redirect(url_for("home", _anchor="suggestions"))


def developer_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not g.current_user:
            return redirect(url_for("login"))
        if not g.current_user["is_developer"] and not is_configured_developer(g.current_user):
            abort(403)
        return view(*args, **kwargs)
    return wrapped_view


@app.route("/developer")
@developer_required
def developer_dashboard():
    conn = get_db_connection()
    today = date.today()
    seven_days_ago = today - timedelta(days=6)
    thirty_days_ago = today - timedelta(days=29)

    metrics = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM users) AS users,
            (SELECT COUNT(*) FROM users WHERE is_active=1) AS active_users,
            (SELECT COUNT(*) FROM users WHERE SUBSTR(created_at, 1, 10)>=?) AS new_users,
            (SELECT COUNT(*) FROM routines) AS routines,
            (SELECT COALESCE(SUM(completed), 0) FROM task_logs) AS completions,
            (SELECT COUNT(*) FROM friends) AS friendships,
            (SELECT COUNT(*) FROM suggestions WHERE status='new') AS new_suggestions,
            (SELECT COALESCE(SUM(latest.solved_count), 0)
             FROM dsa_history AS latest
             WHERE NOT EXISTS (
                SELECT 1
                FROM dsa_history AS newer
                WHERE newer.user_id=latest.user_id
                AND (
                    newer.log_date>latest.log_date
                    OR (newer.log_date=latest.log_date AND newer.id>latest.id)
                )
             )) AS dsa_solved
        """,
        (seven_days_ago.isoformat(),)
    ).fetchone()

    signup_rows = conn.execute(
        """
        SELECT SUBSTR(created_at, 1, 10) AS day, COUNT(*) AS total
        FROM users WHERE SUBSTR(created_at, 1, 10)>=?
        GROUP BY SUBSTR(created_at, 1, 10)
        """,
        (thirty_days_ago.isoformat(),)
    ).fetchall()
    signup_lookup = {row["day"]: row["total"] for row in signup_rows}
    signup_labels = []
    signup_counts = []
    for offset in range(30):
        current_date = thirty_days_ago + timedelta(days=offset)
        signup_labels.append(current_date.strftime("%d %b"))
        signup_counts.append(signup_lookup.get(current_date.isoformat(), 0))

    completion_rows = conn.execute(
        """
        SELECT log_date, COALESCE(SUM(completed), 0) AS total
        FROM task_logs WHERE log_date>=?
        GROUP BY log_date ORDER BY log_date
        """,
        ((today - timedelta(days=13)).isoformat(),)
    ).fetchall()
    completion_lookup = {row["log_date"]: row["total"] for row in completion_rows}
    completion_labels = []
    completion_counts = []
    for offset in range(14):
        current_date = today - timedelta(days=13 - offset)
        completion_labels.append(current_date.strftime("%d %b"))
        completion_counts.append(completion_lookup.get(current_date.isoformat(), 0))

    users = conn.execute(
        """
        SELECT
            users.id, users.username, users.email, users.public_id, users.profile_image,
            users.is_active, users.is_developer, users.created_at, users.last_login_at,
            (SELECT COUNT(*) FROM routines WHERE user_id=users.id) AS routines,
            COALESCE(
                (SELECT solved_count
                 FROM dsa_history
                 WHERE user_id=users.id
                 ORDER BY log_date DESC, id DESC
                 LIMIT 1),
                (SELECT SUM(completed) FROM dsa_topics WHERE user_id=users.id),
                0
            ) AS dsa_solved
        FROM users ORDER BY users.id DESC
        """
    ).fetchall()
    suggestions = conn.execute(
        "SELECT * FROM suggestions ORDER BY id DESC LIMIT 100"
    ).fetchall()
    content_items = conn.execute(
        "SELECT * FROM landing_content ORDER BY display_order, id DESC"
    ).fetchall()
    pinned_notifications = conn.execute(
        "SELECT * FROM developer_notifications ORDER BY is_pinned DESC, id DESC"
    ).fetchall()
    contact_rows = conn.execute(
        "SELECT contact_key, contact_value FROM landing_contact"
    ).fetchall()
    conn.close()

    return render_template(
        "developer/dashboard.html",
        metrics=metrics,
        users=users,
        suggestions=suggestions,
        content_items=content_items,
        signup_labels=signup_labels,
        signup_counts=signup_counts,
        completion_labels=completion_labels,
        completion_counts=completion_counts,
        pinned_notifications=pinned_notifications,
        contact_details=rows_to_contact_details(contact_rows)
    )


@app.route("/developer/users/<int:user_id>/toggle", methods=["POST"])
@developer_required
def developer_toggle_user(user_id):
    if user_id == session["user_id"]:
        flash("You cannot deactivate your own developer account.", "error")
        return redirect(url_for("developer_dashboard", _anchor="users"))
    conn = get_db_connection()
    conn.execute(
        "UPDATE users SET is_active=CASE is_active WHEN 1 THEN 0 ELSE 1 END WHERE id=? AND is_developer=0",
        (user_id,)
    )
    conn.commit()
    conn.close()
    flash("User access updated.", "success")
    return redirect(url_for("developer_dashboard", _anchor="users"))


@app.route("/developer/content", methods=["POST"])
@developer_required
def developer_add_content():
    title = request.form.get("title", "").strip()[:100]
    body = request.form.get("body", "").strip()[:600]
    link_label = request.form.get("link_label", "").strip()[:40]
    link_url = request.form.get("link_url", "").strip()[:300]
    try:
        display_order = int(request.form.get("display_order", 0))
    except ValueError:
        display_order = 0
    if not title or not body:
        flash("Landing updates need a title and description.", "error")
    elif link_url and not link_url.startswith(("http://", "https://", "/", "#")):
        flash("Content links must be an http(s) URL or internal path.", "error")
    else:
        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO landing_content (title, body, link_label, link_url, display_order)
            VALUES (?, ?, ?, ?, ?)
            """,
            (title, body, link_label, link_url, display_order)
        )
        conn.commit()
        conn.close()
        flash("Landing-page update published.", "success")
    return redirect(url_for("developer_dashboard", _anchor="content"))


@app.route("/developer/content/<int:content_id>/update", methods=["POST"])
@developer_required
def developer_update_content(content_id):
    title = request.form.get("title", "").strip()[:100]
    body = request.form.get("body", "").strip()[:600]
    link_label = request.form.get("link_label", "").strip()[:40]
    link_url = request.form.get("link_url", "").strip()[:300]
    try:
        display_order = int(request.form.get("display_order", 0))
    except ValueError:
        display_order = 0
    if not title or not body or (link_url and not link_url.startswith(("http://", "https://", "/", "#"))):
        flash("Check the content title, description, and link.", "error")
    else:
        conn = get_db_connection()
        conn.execute(
            """
            UPDATE landing_content
            SET title=?, body=?, link_label=?, link_url=?, display_order=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (title, body, link_label, link_url, display_order, content_id)
        )
        conn.commit()
        conn.close()
        flash("Landing content updated.", "success")
    return redirect(url_for("developer_dashboard", _anchor="content"))


@app.route("/developer/content/<int:content_id>/toggle", methods=["POST"])
@developer_required
def developer_toggle_content(content_id):
    conn = get_db_connection()
    conn.execute(
        "UPDATE landing_content SET is_published=CASE is_published WHEN 1 THEN 0 ELSE 1 END, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (content_id,)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("developer_dashboard", _anchor="content"))


@app.route("/developer/contact", methods=["POST"])
@developer_required
def developer_update_contact():
    fields = {
        "email": request.form.get("email", "").strip()[:150],
        "phone": request.form.get("phone", "").strip()[:60],
        "location": request.form.get("location", "").strip()[:180],
        "linkedin": request.form.get("linkedin", "").strip()[:300],
        "github": request.form.get("github", "").strip()[:300],
    }
    if fields["email"] and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", fields["email"]):
        flash("Enter a valid contact email.", "error")
        return redirect(url_for("developer_dashboard", _anchor="contact"))
    for key in ("linkedin", "github"):
        if fields[key] and not fields[key].startswith(("http://", "https://")):
            flash("Social links must start with http:// or https://.", "error")
            return redirect(url_for("developer_dashboard", _anchor="contact"))

    conn = get_db_connection()
    for key, value in fields.items():
        conn.execute(
            """
            INSERT INTO landing_contact (contact_key, contact_value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(contact_key) DO UPDATE SET
                contact_value=excluded.contact_value,
                updated_at=CURRENT_TIMESTAMP
            """,
            (key, value)
        )
    conn.commit()
    conn.close()
    flash("Landing contact details updated.", "success")
    return redirect(url_for("developer_dashboard", _anchor="contact"))


@app.route("/developer/notifications/add", methods=["POST"])
@developer_required
def developer_add_notification():
    title = request.form.get("title", "").strip()[:100]
    message = request.form.get("message", "").strip()[:600]
    if not title or not message:
        flash("Notification title and message are required.", "error")
        return redirect(url_for("developer_dashboard", _anchor="pins"))

    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO developer_notifications (title, message, is_pinned)
        VALUES (?, ?, 1)
        """,
        (title, message)
    )
    conn.commit()
    conn.close()
    flash("Pinned notification published.", "success")
    return redirect(url_for("developer_dashboard", _anchor="pins"))


@app.route("/developer/notifications/<int:notification_id>/update", methods=["POST"])
@developer_required
def developer_update_notification(notification_id):
    title = request.form.get("title", "").strip()[:100]
    message = request.form.get("message", "").strip()[:600]
    if not title or not message:
        flash("Notification title and message are required.", "error")
        return redirect(url_for("developer_dashboard", _anchor="pins"))

    conn = get_db_connection()
    conn.execute(
        """
        UPDATE developer_notifications
        SET title=?, message=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (title, message, notification_id)
    )
    conn.commit()
    conn.close()
    flash("Pinned notification updated.", "success")
    return redirect(url_for("developer_dashboard", _anchor="pins"))


@app.route("/developer/notifications/<int:notification_id>/toggle", methods=["POST"])
@developer_required
def developer_toggle_notification(notification_id):
    conn = get_db_connection()
    conn.execute(
        """
        UPDATE developer_notifications
        SET is_pinned=CASE is_pinned WHEN 1 THEN 0 ELSE 1 END,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (notification_id,)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("developer_dashboard", _anchor="pins"))


@app.route("/developer/notifications/<int:notification_id>/delete", methods=["POST"])
@developer_required
def developer_delete_notification(notification_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM developer_notifications WHERE id=?", (notification_id,))
    conn.commit()
    conn.close()
    flash("Pinned notification deleted.", "success")
    return redirect(url_for("developer_dashboard", _anchor="pins"))


@app.route("/developer/suggestions/<int:suggestion_id>/delete", methods=["POST"])
@developer_required
def developer_delete_suggestion(suggestion_id):
    conn = get_db_connection()
    deleted = conn.execute(
        "DELETE FROM suggestions WHERE id=? AND status='resolved'",
        (suggestion_id,)
    )
    conn.commit()
    conn.close()
    flash("Resolved suggestion removed.", "success")
    return redirect(url_for("developer_dashboard", _anchor="suggestions"))


@app.route("/developer/suggestions/<int:suggestion_id>/status", methods=["POST"])
@developer_required
def developer_suggestion_status(suggestion_id):
    status = request.form.get("status", "new")
    if status not in {"new", "reviewed", "resolved"}:
        abort(400)
    conn = get_db_connection()
    conn.execute("UPDATE suggestions SET status=? WHERE id=?", (status, suggestion_id))
    conn.commit()
    conn.close()
    return redirect(url_for("developer_dashboard", _anchor="suggestions"))

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    today = date.today()
    selected_day = parse_iso_date(request.args.get("date"), today)
    today_key = selected_day.isoformat()
    conn = get_db_connection()

    user = conn.execute(
        "SELECT id, username, profile_image FROM users WHERE id=?",
        (user_id,)
    ).fetchone()

    routine_state = get_dashboard_routine_state(conn, user_id, selected_day)
    routines = routine_state["routines"]
    total = routine_state["total"]
    completed = routine_state["completed"]
    progress = routine_state["progress"]

    seven_days_ago = today - timedelta(days=6)
    weekly_rows = conn.execute(
        """
        SELECT task_logs.log_date, COALESCE(SUM(task_logs.completed), 0) AS completed
        FROM task_logs
        JOIN routines ON routines.id=task_logs.routine_id
        WHERE routines.user_id=? AND task_logs.log_date>=?
        GROUP BY task_logs.log_date
        """,
        (user_id, seven_days_ago.isoformat())
    ).fetchall()
    weekly_lookup = {row["log_date"]: int(row["completed"]) for row in weekly_rows}
    weekly_labels = []
    weekly_rates = []
    for offset in range(7):
        current_date = seven_days_ago + timedelta(days=offset)
        weekly_labels.append(current_date.strftime("%a"))
        weekly_rates.append(
            min(round((weekly_lookup.get(current_date.isoformat(), 0) / total) * 100), 100)
            if total else 0
        )

    dsa_summary = conn.execute(
        """
        SELECT
            COALESCE(SUM(completed), 0) AS completed,
            COALESCE(SUM(target), 0) AS target
        FROM dsa_topics
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchone()
    latest_dsa = conn.execute(
        """
        SELECT solved_count FROM dsa_history
        WHERE user_id=? ORDER BY log_date DESC LIMIT 1
        """,
        (user_id,)
    ).fetchone()
    social_summary = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM friends WHERE user1_id=? OR user2_id=?) AS friends,
            (SELECT COUNT(*) FROM challenges
             WHERE status='active' AND (challenger_id=? OR challenged_id=?)) AS challenges
        """,
        (user_id, user_id, user_id, user_id)
    ).fetchone()

    pending_routines = [routine for routine in routines if not routine["completed"]]
    dismissed_keys = get_dismissed_notification_keys(conn, user_id)
    ai_notifications = [
        note for note in build_ai_notifications(pending_routines, selected_day, progress)
        if note["key"] not in dismissed_keys
    ]
    pinned_notifications = conn.execute(
        """
        SELECT id, title, message, created_at
        FROM developer_notifications
        WHERE is_pinned=1
        ORDER BY id DESC
        LIMIT 3
        """
    ).fetchall()
    streak = calculate_streak_from_conn(conn, user_id)
    conn.close()

    return render_template(
        "dashboard/dashboard.html",

        routines=routines,

        total=total,

        completed=completed,

        progress=progress,
        streak=streak,
        user=user,
        focus_task=routine_state["focus_task"],
        pending=routine_state["pending"],
        selected_date=today_key,
        selected_day=selected_day,
        is_today=selected_day == today,
        previous_day=(selected_day - timedelta(days=1)).isoformat(),
        next_day=(selected_day + timedelta(days=1)).isoformat(),
        today_label=selected_day.strftime("%A, %d %B"),
        weekly_labels=weekly_labels,
        weekly_rates=weekly_rates,
        dsa_completed=dsa_summary["completed"],
        dsa_target=dsa_summary["target"],
        leetcode_total=latest_dsa["solved_count"] if latest_dsa else 0,
        friend_count=social_summary["friends"],
        active_challenges=social_summary["challenges"],
        ai_notifications=ai_notifications,
        pinned_notifications=pinned_notifications
    )
@app.route(
    "/login",
    methods=["GET","POST"]
)

def login():
    if g.current_user:
        return redirect(url_for("dashboard"))

    error = None
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")
        conn = get_db_connection()
        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE LOWER(username)=LOWER(?)
            OR LOWER(email)=LOWER(?)
            OR LOWER(public_id)=LOWER(?)
            """,
            (identifier, identifier, identifier)
        ).fetchone()

        if user and not user["is_active"]:
            error = "This account is currently disabled. Contact the developer."
        elif user and check_password_hash(user["password"], password):
            user = ensure_developer_access(conn, user)
            conn.execute(
                "UPDATE users SET last_login_at=CURRENT_TIMESTAMP WHERE id=?",
                (user["id"],)
            )
            conn.commit()
            session.clear()
            session["user_id"] = user["id"]
            refresh_session_user(user)
            session.permanent = True
            conn.close()
            return redirect(url_for("dashboard"))
        elif not error:
            error = "The username, email, Student ID, or password is incorrect."
        conn.close()

    return render_template(
        "auth/login.html",
        error=error
    )


@app.route("/guide")
def guide():
    if "user_id" not in session:
        return redirect("/login")
    return render_template("guide/guide.html")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if g.current_user:
        return redirect(url_for("dashboard"))

    error = None
    success = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        public_id = request.form.get("public_id", "").strip().lower()
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            error = "Enter the email address on your account."
        elif not public_id:
            error = "Enter your Student ID."
        elif len(new_password) < 8:
            error = "New password must be at least 8 characters."
        elif new_password != confirm_password:
            error = "Passwords do not match."
        else:
            conn = get_db_connection()
            user = conn.execute(
                """
                SELECT id
                FROM users
                WHERE LOWER(email)=LOWER(?) AND LOWER(public_id)=LOWER(?)
                """,
                (email, public_id)
            ).fetchone()
            if user:
                conn.execute(
                    "UPDATE users SET password=? WHERE id=?",
                    (generate_password_hash(new_password), user["id"])
                )
                conn.commit()
                success = "Password reset successfully. You can sign in now."
            else:
                error = "No account matches that email and Student ID."
            conn.close()

    return render_template(
        "auth/forgot_password.html",
        error=error,
        success=success
    )


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))
@app.route(
    "/register",
    methods=["GET","POST"]
)

def register():
    if g.current_user:
        return redirect(url_for("dashboard"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]{2,29}", username):
            error = "Username must be 3-30 characters and use letters, numbers, spaces, dots, dashes, or underscores."
        elif not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            error = "Enter a valid email address."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif password != confirm_password:
            error = "Passwords do not match."

        conn = get_db_connection() if not error else None
        existing_user = conn.execute(
            """
            SELECT 1
            FROM users
            WHERE LOWER(username)=LOWER(?)
            OR LOWER(email)=LOWER(?)
            """,
            (username, email)
        ).fetchone() if conn else None

        if existing_user:
            error = "An account already uses that username or email."

        if conn and not error:
            conn.execute(
                """
                INSERT INTO users (username, email, password, public_id, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (username, email, generate_password_hash(password), generate_public_id(conn, username))
            )
            conn.commit()
            conn.close()
            flash("Account created. You can now sign in.", "success")
            return redirect(url_for("login"))

        if conn:
            conn.close()

    return render_template(
        "auth/register.html",
        error=error
    )


@app.route("/analytics")
def analytics():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    conn = get_db_connection()

    routines = conn.execute(
        """
        SELECT
            routines.id,
            routines.task_name,
            COALESCE(task_logs.completed, 0) AS completed
        FROM routines
        LEFT JOIN task_logs
            ON task_logs.routine_id=routines.id
            AND task_logs.log_date=?
        WHERE routines.user_id=?
        ORDER BY routines.id DESC
        """,
        (date.today().isoformat(), user_id)
    ).fetchall()
    total = len(routines)
    completed = sum(routine["completed"] for routine in routines)
    progress = round((completed / total) * 100) if total else 0
    streak = calculate_streak(user_id)

    start_date = date.today() - timedelta(days=13)
    daily_rows = conn.execute(
        """
        SELECT
            task_logs.log_date,
            COUNT(*) AS logged_count,
            COALESCE(SUM(task_logs.completed), 0) AS completed_count
        FROM task_logs
        JOIN routines ON routines.id=task_logs.routine_id
        WHERE routines.user_id=? AND task_logs.log_date>=?
        GROUP BY task_logs.log_date
        """,
        (user_id, start_date.isoformat())
    ).fetchall()
    daily_lookup = {row["log_date"]: row for row in daily_rows}

    labels = []
    completion_data = []
    completion_rates = []
    consistency_days = 0
    for offset in range(14):
        current_date = start_date + timedelta(days=offset)
        row = daily_lookup.get(current_date.isoformat())
        completed_count = int(row["completed_count"]) if row else 0
        labels.append(current_date.strftime("%d %b"))
        completion_data.append(completed_count)
        completion_rates.append(
            min(round((completed_count / total) * 100), 100)
            if total else 0
        )
        if completed_count:
            consistency_days += 1

    habit_performance = conn.execute(
        """
        SELECT
            routines.task_name,
            COUNT(task_logs.id) AS logged_days,
            COALESCE(SUM(task_logs.completed), 0) AS completed_days
        FROM routines
        LEFT JOIN task_logs
            ON task_logs.routine_id=routines.id
            AND task_logs.log_date>=?
        WHERE routines.user_id=?
        GROUP BY routines.id
        ORDER BY completed_days DESC, routines.task_name
        """,
        (start_date.isoformat(), user_id)
    ).fetchall()

    habit_performance = [dict(item) for item in habit_performance]
    for item in habit_performance:
        item["rate"] = (
            round((item["completed_days"] / item["logged_days"]) * 100)
            if item["logged_days"] else 0
        )

    habit_performance.sort(
        key=lambda item: (item["rate"], item["completed_days"]),
        reverse=True
    )
    best_habit = habit_performance[0] if habit_performance else None
    needs_attention = min(habit_performance, key=lambda item: item["rate"]) if habit_performance else None

    dsa_history = conn.execute(
        """
        SELECT solved_count, log_date
        FROM dsa_history
        WHERE user_id=? AND log_date>=?
        ORDER BY log_date
        """,
        (user_id, start_date.isoformat())
    ).fetchall()
    dsa_growth = (
        max(int(dsa_history[-1]["solved_count"]) - int(dsa_history[0]["solved_count"]), 0)
        if len(dsa_history) > 1 else 0
    )

    conn.close()

    total_completions = sum(completion_data)
    average_rate = round(sum(completion_rates) / 14)
    best_day_index = completion_data.index(max(completion_data)) if total_completions else None
    best_day = labels[best_day_index] if best_day_index is not None else "No activity yet"

    return render_template(
        "dashboard/analytics.html",
        total=total,
        completed=completed,
        progress=progress,
        streak=streak,
        labels=labels,
        completion_data=completion_data,
        completion_rates=completion_rates,
        total_completions=total_completions,
        average_rate=average_rate,
        consistency_days=consistency_days,
        best_day=best_day,
        best_habit=best_habit,
        needs_attention=needs_attention,
        habit_performance=habit_performance,
        dsa_growth=dsa_growth
    )


@app.route("/calendar")
def calendar():

    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]

    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
        if year < 2000 or year > 2100 or month < 1 or month > 12:
            raise ValueError
    except (TypeError, ValueError):
        return "Invalid calendar month", 400

    conn = get_db_connection()

    month_start = date(year, month, 1)
    month_end = date(year, month, cal.monthrange(year, month)[1])
    routine_count = conn.execute(
        "SELECT COUNT(*) AS total FROM routines WHERE user_id=?",
        (user_id,)
    ).fetchone()["total"]

    logs = conn.execute(
        """
        SELECT
            tl.log_date,
            COALESCE(SUM(tl.completed), 0) AS completed_count
        FROM task_logs tl
        JOIN routines r
            ON tl.routine_id = r.id
        WHERE r.user_id = ?
        AND tl.log_date BETWEEN ? AND ?
        GROUP BY tl.log_date
        """,
        (user_id, month_start.isoformat(), month_end.isoformat())
    ).fetchall()

    conn.close()

    activity = {
        row["log_date"]: {
            "completed": int(row["completed_count"] or 0),
            "rate": min(round((int(row["completed_count"] or 0) / routine_count) * 100), 100)
            if routine_count else 0
        }
        for row in logs
    }

    month_grid = cal.monthcalendar(
        year,
        month
    )

    month_name = cal.month_name[
        month
    ]

    previous_date = month_start - timedelta(days=1)
    next_date = month_end + timedelta(days=1)
    month_completions = sum(item["completed"] for item in activity.values())
    active_days = sum(1 for item in activity.values() if item["completed"] > 0)
    perfect_days = sum(
        1 for item in activity.values()
        if routine_count and item["completed"] >= routine_count
    )

    return render_template(
        "dashboard/calendar.html",

        cal=month_grid,

        activity=activity,

        month_name=month_name,

        year=year,
        month=month,
        today_key=today.isoformat(),
        previous_year=previous_date.year,
        previous_month=previous_date.month,
        next_year=next_date.year,
        next_month=next_date.month,
        routine_count=routine_count,
        month_completions=month_completions,
        active_days=active_days,
        perfect_days=perfect_days
    )

@app.route("/calendar_day/<date>")
def calendar_day(date):

    if "user_id" not in session:
        return {"error": "Authentication required"}, 401

    try:
        selected_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return {"error": "Invalid date"}, 400

    conn = get_db_connection()

    tasks = conn.execute(
        """
        SELECT
            r.task_name,
            COALESCE(tl.completed, 0) AS completed
        FROM routines r
        LEFT JOIN task_logs tl
            ON tl.routine_id = r.id
            AND tl.log_date = ?
        WHERE r.user_id = ?
        ORDER BY r.id
        """,
        (
            selected_date.isoformat(),
            session["user_id"]
        )
    ).fetchall()

    conn.close()

    return {
        "tasks": [
            {
                "name": row["task_name"],
                "completed": row["completed"]
            }
            for row in tasks
        ]
    }

@app.route("/leaderboard")
def leaderboard():

    if "user_id" not in session:

        return redirect("/login")

    start_date = date.today() - timedelta(days=6)
    conn = get_db_connection()
    users = conn.execute(
        """
        SELECT
            users.id,
            users.username,
            users.profile_image,
            users.college,
            (SELECT COUNT(*) FROM routines WHERE user_id=users.id) AS routine_count,
            COALESCE((
                SELECT SUM(task_logs.completed)
                FROM task_logs
                JOIN routines ON routines.id=task_logs.routine_id
                WHERE routines.user_id=users.id AND task_logs.log_date>=?
            ), 0) AS weekly_completions,
            COALESCE((
                SELECT solved_count FROM dsa_history
                WHERE user_id=users.id
                ORDER BY log_date DESC LIMIT 1
            ), 0) AS latest_dsa,
            COALESCE((
                SELECT solved_count FROM dsa_history
                WHERE user_id=users.id AND log_date>=?
                ORDER BY log_date ASC LIMIT 1
            ), 0) AS first_dsa
        FROM users
        WHERE users.id=?
        OR EXISTS (
            SELECT 1 FROM friends
            WHERE (friends.user1_id=? AND friends.user2_id=users.id)
               OR (friends.user2_id=? AND friends.user1_id=users.id)
        )
        ORDER BY users.username
        """,
        (start_date.isoformat(), start_date.isoformat(), session["user_id"], session["user_id"], session["user_id"])
    ).fetchall()
    conn.close()

    leaderboard_data = []
    for row in users:
        user = dict(row)
        possible_completions = user["routine_count"] * 7
        habit_rate = (
            min(round((user["weekly_completions"] / possible_completions) * 100), 100)
            if possible_completions else 0
        )
        dsa_growth = max(int(user["latest_dsa"]) - int(user["first_dsa"]), 0) if user["first_dsa"] else 0
        streak = calculate_streak(user["id"])
        dsa_score = min(dsa_growth * 10, 100)
        streak_score = min(round((streak / 7) * 100), 100)
        user.update({
            "habit_rate": habit_rate,
            "dsa_growth": dsa_growth,
            "streak": streak,
            "score": round(habit_rate * 0.65 + dsa_score * 0.20 + streak_score * 0.15),
            "is_current_user": user["id"] == session["user_id"]
        })
        leaderboard_data.append(user)

    leaderboard_data.sort(
        key=lambda user: (user["score"], user["habit_rate"], user["dsa_growth"]),
        reverse=True
    )
    for index, user in enumerate(leaderboard_data, start=1):
        user["rank"] = index

    current_entry = next(
        (user for user in leaderboard_data if user["is_current_user"]),
        None
    )

    return render_template(
        "friends/leaderboard.html",
        leaderboard_data=leaderboard_data,
        current_entry=current_entry,
        participant_count=len(leaderboard_data),
        period_start=start_date.strftime("%d %b")
    )
@app.route("/notifications")
def notifications():

    if "user_id" not in session:

        return redirect("/login")

    conn = get_db_connection()

    selected_day = date.today()
    today_key = selected_day.isoformat()
    routines = conn.execute(
        """
        SELECT routines.id, routines.task_name, COALESCE(task_logs.completed, 0) AS completed
        FROM routines
        LEFT JOIN task_logs
            ON task_logs.routine_id=routines.id
            AND task_logs.log_date=?
        WHERE routines.user_id=?
        ORDER BY routines.id DESC
        """,
        (today_key, session["user_id"])
    ).fetchall()
    total = len(routines)
    completed = sum(int(routine["completed"]) for routine in routines)
    progress = round((completed / total) * 100) if total else 0
    dismissed_keys = get_dismissed_notification_keys(conn, session["user_id"])
    ai_notifications = [
        note for note in build_ai_notifications(
            [routine for routine in routines if not routine["completed"]],
            selected_day,
            progress
        )
        if note["key"] not in dismissed_keys
    ]
    pinned_notifications = conn.execute(
        """
        SELECT id, title, message, created_at
        FROM developer_notifications
        WHERE is_pinned=1
        ORDER BY id DESC
        """
    ).fetchall()
    user_notifications = conn.execute(
        """
        SELECT *
        FROM notifications
        WHERE user_id=?
        ORDER BY id DESC
        """,
        (session["user_id"],)
    ).fetchall()

    conn.close()

    return render_template(
        "dashboard/notifications.html",
        notifications=user_notifications,
        ai_notifications=ai_notifications,
        pinned_notifications=pinned_notifications
    )


@app.route("/notifications/clear", methods=["POST"])
def clear_notifications():
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()
    conn.execute(
        "DELETE FROM notifications WHERE user_id=?",
        (session["user_id"],)
    )
    conn.commit()
    conn.close()
    flash("Your account notifications were cleared.", "success")
    return redirect(url_for("notifications"))


@app.route("/notifications/ai-dismiss", methods=["POST"])
def dismiss_ai_notification():
    if "user_id" not in session:
        return redirect("/login")

    notification_key = request.form.get("notification_key", "").strip()
    next_url = request.form.get("next", url_for("notifications"))

    if not re.fullmatch(r"ai-[A-Za-z0-9_.:-]{1,100}", notification_key):
        abort(400)

    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO notification_dismissals (user_id, notification_key, dismissed_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, notification_key)
        DO UPDATE SET dismissed_at=CURRENT_TIMESTAMP
        """,
        (session["user_id"], notification_key)
    )
    conn.commit()
    conn.close()

    flash("AI notification removed.", "success")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = url_for("notifications")
    return redirect(next_url)


@app.route("/notifications/<int:notification_id>/delete", methods=["POST"])
def delete_notification(notification_id):
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()
    conn.execute(
        "DELETE FROM notifications WHERE id=? AND user_id=?",
        (notification_id, session["user_id"])
    )
    conn.commit()
    conn.close()
    flash("Notification removed.", "success")
    return redirect(url_for("notifications"))
@app.route(
    "/search-users",
    methods=["GET","POST"]
)
def search_users():

    if "user_id" not in session:

        return redirect("/login")

    query = request.form.get("query", "") if request.method == "POST" else request.args.get("query", "")
    return redirect(url_for("friends_hub", student_id=query.strip()))
@app.route("/profile", methods=["GET", "POST"])
def profile():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id=?
        """,
        (session["user_id"],)
    ).fetchone()

    if request.method == "POST":
        bio = request.form.get("bio", "").strip()[:300]
        college = request.form.get("college", "").strip()[:120]
        branch = request.form.get("branch", "").strip()[:80]
        year = request.form.get("year", "").strip()[:30]
        github = request.form.get("github", "").strip()[:250]
        linkedin = request.form.get("linkedin", "").strip()[:250]
        leetcode = request.form.get("leetcode", "").strip()[:250]

        links = (github, linkedin, leetcode)
        if any(link and not link.startswith(("http://", "https://")) for link in links):
            flash("Professional links must start with http:// or https://.", "error")
            conn.close()
            return redirect(url_for("profile"))

        uploaded_file = request.files.get("profile_image")
        image_path = user["profile_image"]

        if uploaded_file and uploaded_file.filename:
            safe_name = secure_filename(uploaded_file.filename)
            extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
            detected_type = detect_profile_image_type(uploaded_file)
            expected_type = "jpeg" if extension in {"jpg", "jpeg"} else extension
            if (
                extension not in ALLOWED_PROFILE_EXTENSIONS
                or uploaded_file.mimetype not in ALLOWED_PROFILE_MIMES
                or detected_type != expected_type
            ):
                flash("Upload a PNG, JPG, or WebP profile image.", "error")
                conn.close()
                return redirect(url_for("profile"))

            image_path = profile_image_data_url(uploaded_file, detected_type)

        conn.execute(
            """
            UPDATE users
            SET
                profile_image=?,
                bio=?,
                college=?,
                branch=?,
                year=?,
                github=?,
                linkedin=?,
                leetcode=?
            WHERE id=?
            """,
            (
                image_path,
                bio,
                college,
                branch,
                year,
                github,
                linkedin,
                leetcode,
                session["user_id"]
            )
        )

        conn.commit()
        updated_user = dict(user)
        updated_user["profile_image"] = image_path
        refresh_session_user(updated_user)
        conn.close()
        flash("Public profile updated.", "success")
        return redirect(url_for("profile"))

    profile_fields = [
        user["profile_image"],
        user["bio"],
        user["college"],
        user["branch"],
        user["year"],
        user["github"],
        user["linkedin"],
        user["leetcode"]
    ]

    filled_fields = sum(
        1 for field in profile_fields
        if field
    )

    completion_percentage = int(
        (filled_fields / len(profile_fields)) * 100
    )

    conn.close()

    return render_template(
        "profile/profile.html",
        user=user,
        completion_percentage=completion_percentage
    )
@app.route(
    "/settings",
    methods=["GET","POST"]
)
def settings():

    if "user_id" not in session:

        return redirect("/login")

    conn = get_db_connection()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id=?
        """,
        (session["user_id"],)
    ).fetchone()

    if request.method == "POST":
        action = request.form.get("action")
        current_password = request.form.get("current_password", "")

        if action == "suggestion":
            message = request.form.get("message", "").strip()[:1200]
            if len(message) < 10:
                flash("Suggestion must be at least 10 characters.", "error")
            else:
                conn.execute(
                    """
                    INSERT INTO suggestions (user_id, name, email, message)
                    VALUES (?, ?, ?, ?)
                    """,
                    (session["user_id"], user["username"], user["email"], message)
                )
                conn.commit()
                flash("Suggestion sent to the developer.", "success")
            conn.close()
            return redirect(url_for("settings"))

        if not check_password_hash(user["password"], current_password):
            flash("Current password is incorrect.", "error")
            conn.close()
            return redirect(url_for("settings"))

        if action == "account":
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip().lower()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]{2,29}", username):
                flash("Username must be 3-30 valid characters.", "error")
            elif not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                flash("Enter a valid email address.", "error")
            else:
                duplicate = conn.execute(
                    """
                    SELECT 1 FROM users
                    WHERE id!=? AND (LOWER(username)=LOWER(?) OR LOWER(email)=LOWER(?))
                    """,
                    (session["user_id"], username, email)
                ).fetchone()
                if duplicate:
                    flash("That username or email is already in use.", "error")
                else:
                    conn.execute(
                        "UPDATE users SET username=?, email=? WHERE id=?",
                        (username, email, session["user_id"])
                    )
                    conn.commit()
                    updated_user = dict(user)
                    updated_user["username"] = username
                    updated_user["email"] = email
                    refresh_session_user(updated_user)
                    flash("Account details updated.", "success")

        elif action == "password":
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")
            if len(new_password) < 8:
                flash("New password must be at least 8 characters.", "error")
            elif new_password != confirm_password:
                flash("New passwords do not match.", "error")
            elif check_password_hash(user["password"], new_password):
                flash("Choose a password different from your current password.", "error")
            else:
                conn.execute(
                    "UPDATE users SET password=? WHERE id=?",
                    (generate_password_hash(new_password), session["user_id"])
                )
                conn.commit()
                flash("Password changed successfully.", "success")
        elif action == "delete_data":
            confirmation = request.form.get("confirmation", "").strip()
            if confirmation != "DELETE DATA":
                flash("Type DELETE DATA exactly to clear your progress.", "error")
            else:
                delete_user_progress(conn, session["user_id"])
                conn.commit()
                flash("Your progress, challenges, and activity data were deleted.", "success")
        elif action == "delete_account":
            confirmation = request.form.get("confirmation", "").strip()
            if confirmation != "DELETE ACCOUNT":
                flash("Type DELETE ACCOUNT exactly to delete your profile.", "error")
            else:
                delete_user_account(conn, session["user_id"])
                conn.commit()
                conn.close()
                session.clear()
                flash("Your account and profile were deleted.", "success")
                return redirect(url_for("login"))
        else:
            flash("Unknown settings action.", "error")

        conn.close()
        return redirect(url_for("settings"))

    conn.close()

    return render_template(
        "profile/settings.html",
        user=user
    )
@app.route(
    "/add_routine",
    methods=["POST"]
)
def add_routine():

    if "user_id" not in session:
        return redirect("/login")

    task = request.form.get("task", "").strip()[:100]
    selected_day = parse_iso_date(request.form.get("selected_date"), date.today())
    message = None

    if task:

        conn = get_db_connection()

        existing = conn.execute(
            "SELECT 1 FROM routines WHERE user_id=? AND LOWER(task_name)=LOWER(?)",
            (session["user_id"], task)
        ).fetchone()

        if not existing:
            conn.execute(
            """
            INSERT INTO routines
            (
                user_id,
                task_name,
                completed
            )
            VALUES (?,?,0)
            """,
            (
                session["user_id"],
                task
            )
            )
            message = "Routine added."
        else:
            message = "That routine already exists."

        conn.commit()

        if wants_json_response():
            response = dashboard_routine_json(conn, session["user_id"], selected_day, message)
            conn.close()
            return response

        conn.close()

    elif wants_json_response():
        conn = get_db_connection()
        response = dashboard_routine_json(conn, session["user_id"], selected_day, "Enter a routine first.")
        conn.close()
        return response

    return redirect_dashboard_for(selected_day)

@app.route("/delete/<int:id>", methods=["POST"])
def delete(id):

    if "user_id" not in session:

        return redirect("/login")

    selected_day = parse_iso_date(request.form.get("selected_date"), date.today())
    conn = get_db_connection()

    conn.execute(
        """
        DELETE FROM task_logs
        WHERE routine_id=?
        AND EXISTS (
            SELECT 1 FROM routines
            WHERE routines.id=? AND routines.user_id=?
        )
        """,
        (id, id, session["user_id"])
    )

    conn.execute(
        """
        DELETE FROM routines
        WHERE id=?
        AND user_id=?
        """,
        (
            id,
            session["user_id"]
        )
    )

    conn.commit()

    if wants_json_response():
        response = dashboard_routine_json(conn, session["user_id"], selected_day, "Routine deleted.")
        conn.close()
        return response

    conn.close()

    return redirect_dashboard_for(selected_day)
@app.route("/toggle/<int:id>", methods=["POST"])
def toggle(id):

    if "user_id" not in session:
        return redirect("/login")

    selected_day = parse_iso_date(request.form.get("selected_date"), date.today())
    conn = get_db_connection()

    routine = conn.execute(
        """
        SELECT *
        FROM routines
        WHERE id=?
        AND user_id=?
        """,
        (
            id,
            session["user_id"]
        )
    ).fetchone()

    if not routine:

        if wants_json_response():
            response = dashboard_routine_json(conn, session["user_id"], selected_day, "Routine was not found.")
            conn.close()
            return response

        conn.close()

        return redirect_dashboard_for(selected_day)

    log_date = selected_day.isoformat()

    existing_log = conn.execute(
        """
        SELECT * FROM task_logs
        WHERE routine_id=? AND log_date=?
        """,
        (id, log_date)
    ).fetchone()

    current_status = int(existing_log["completed"]) if existing_log else 0
    new_status = 0 if current_status else 1

    if existing_log:

        conn.execute(
            """
            UPDATE task_logs
            SET completed=?
            WHERE id=?
            """,
            (
                new_status,
                existing_log["id"]
            )
        )

    else:

        conn.execute(
            """
            INSERT INTO task_logs
            (
                routine_id,
                log_date,
                completed
            )
            VALUES (?,?,?)
            """,
            (
                id,
                log_date,
                new_status
            )
        )

    conn.commit()

    if wants_json_response():
        message = "Routine completed." if new_status else "Routine marked incomplete."
        response = dashboard_routine_json(conn, session["user_id"], selected_day, message)
        conn.close()
        return response

    conn.close()

    return redirect_dashboard_for(selected_day)

# =========================================
# FRIENDS HUB
# =========================================

@app.route("/friends-hub")
def friends_hub():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    current_user = session["user_id"]

    current_user_row = conn.execute(
        "SELECT id, username, public_id FROM users WHERE id=?",
        (current_user,)
    ).fetchone()

    search_query = request.args.get("student_id", "").strip()
    search_result = None
    search_notice = None

    if search_query:
        search_result = conn.execute(
            """
            SELECT id, username, public_id, college, bio
            FROM users
            WHERE LOWER(public_id)=LOWER(?)
            AND id!=?
            AND is_active=1
            """,
            (search_query, current_user)
        ).fetchone()

        if search_result:
            search_result = dict(search_result)
            session["last_profile_search_id"] = search_result["id"]
            friendship = conn.execute(
                """
                SELECT 1 FROM friends
                WHERE (user1_id=? AND user2_id=?) OR (user1_id=? AND user2_id=?)
                """,
                (current_user, search_result["id"], search_result["id"], current_user)
            ).fetchone()
            request_state = conn.execute(
                """
                SELECT id, sender_id, receiver_id, status
                FROM friend_requests
                WHERE status='pending'
                AND ((sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?))
                """,
                (current_user, search_result["id"], search_result["id"], current_user)
            ).fetchone()

            if friendship:
                search_result["relationship"] = "friend"
            elif request_state and request_state["sender_id"] == current_user:
                search_result["relationship"] = "sent"
            elif request_state:
                search_result["relationship"] = "received"
                search_result["request_id"] = request_state["id"]
            else:
                search_result["relationship"] = "available"
        else:
            search_notice = "No active student was found with that exact User ID."

    developer_users = conn.execute(
        """
        SELECT id, username, college, bio
        FROM users
        WHERE is_developer=1
        AND is_active=1
        AND id!=?
        ORDER BY username
        """,
        (current_user,)
    ).fetchall()

    # =========================
    # FRIENDS
    # =========================

    friends = conn.execute("""

        SELECT
            users.*,
            COALESCE((
                SELECT SUM(dsa_topics.completed)
                FROM dsa_topics
                WHERE dsa_topics.user_id = users.id
            ), 0) AS dsa_solved,
            COALESCE((
                SELECT SUM(task_logs.completed)
                FROM task_logs
                JOIN routines ON routines.id = task_logs.routine_id
                WHERE routines.user_id = users.id
            ), 0) AS habits_completed,
            COALESCE((
                SELECT COUNT(*) FROM challenges
                WHERE challenges.winner_id = users.id
            ), 0) AS challenge_wins

        FROM friends

        JOIN users

        ON (
            users.id = friends.user1_id
            OR
            users.id = friends.user2_id
        )

        WHERE
        (
            friends.user1_id = ?
            OR
            friends.user2_id = ?
        )

        AND users.id != ?

        ORDER BY users.username
    """, (

        current_user,
        current_user,
        current_user

    )).fetchall()

    # =========================
    # FRIEND REQUESTS
    # =========================

    requests = conn.execute("""

        SELECT
            friend_requests.id,
            users.id AS profile_user_id,
            users.username,
            users.profile_image,
            users.college,
            users.id AS sender_id

        FROM friend_requests

        JOIN users

        ON users.id = friend_requests.sender_id

        WHERE friend_requests.receiver_id = ?
        AND friend_requests.status = 'pending'

    """, (current_user,)).fetchall()

    # =========================
    # ACTIVITY FEED
    # =========================

    routine_activity = conn.execute(
        """
        SELECT
            users.id AS profile_user_id,
            users.username,
            users.profile_image,
            'Routine completed' AS title,
            routines.task_name || ' was completed for ' || task_logs.log_date AS activity,
            task_logs.log_date AS created_at,
            'Habit' AS kind
        FROM task_logs
        JOIN routines ON routines.id = task_logs.routine_id
        JOIN users ON users.id = routines.user_id
        WHERE task_logs.completed=1
        AND (
            routines.user_id=?
            OR EXISTS (
                SELECT 1 FROM friends
                WHERE (friends.user1_id=? AND friends.user2_id=routines.user_id)
                   OR (friends.user2_id=? AND friends.user1_id=routines.user_id)
            )
        )
        ORDER BY task_logs.log_date DESC
        LIMIT 8
        """,
        (current_user, current_user, current_user)
    ).fetchall()

    dsa_activity = conn.execute(
        """
        SELECT
            users.id AS profile_user_id,
            users.username,
            users.profile_image,
            'DSA progress logged' AS title,
            'Recorded ' || dsa_history.solved_count || ' solved problems on ' || dsa_history.log_date AS activity,
            dsa_history.log_date AS created_at,
            'DSA' AS kind
        FROM dsa_history
        JOIN users ON users.id = dsa_history.user_id
        WHERE dsa_history.user_id=?
        OR EXISTS (
            SELECT 1 FROM friends
            WHERE (friends.user1_id=? AND friends.user2_id=dsa_history.user_id)
               OR (friends.user2_id=? AND friends.user1_id=dsa_history.user_id)
        )
        ORDER BY dsa_history.log_date DESC
        LIMIT 6
        """,
        (current_user, current_user, current_user)
    ).fetchall()

    challenge_activity = conn.execute(
        """
        SELECT
            challenger.id AS profile_user_id,
            challenger.username,
            challenger.profile_image,
            'Challenge started' AS title,
            challenger.username || ' challenged ' || challenged.username AS activity,
            challenges.created_at,
            'Challenge' AS kind
        FROM challenges
        JOIN users AS challenger ON challenger.id = challenges.challenger_id
        JOIN users AS challenged ON challenged.id = challenges.challenged_id
        WHERE challenges.challenger_id=? OR challenges.challenged_id=?
        OR EXISTS (
            SELECT 1 FROM friends
            WHERE (friends.user1_id=? AND friends.user2_id=challenges.challenger_id)
               OR (friends.user2_id=? AND friends.user1_id=challenges.challenger_id)
               OR (friends.user1_id=? AND friends.user2_id=challenges.challenged_id)
               OR (friends.user2_id=? AND friends.user1_id=challenges.challenged_id)
        )
        ORDER BY challenges.created_at DESC
        LIMIT 6
        """,
        (current_user, current_user, current_user, current_user, current_user, current_user)
    ).fetchall()

    connection_activity = conn.execute(
        """
        SELECT
            users.id AS profile_user_id,
            users.username,
            users.profile_image,
            'New connection' AS title,
            users.username || ' joined your student circle' AS activity,
            CURRENT_TIMESTAMP AS created_at,
            'Network' AS kind
        FROM friends
        JOIN users ON users.id = CASE
            WHEN friends.user1_id=? THEN friends.user2_id
            ELSE friends.user1_id
        END
        WHERE friends.user1_id=? OR friends.user2_id=?
        ORDER BY friends.id DESC
        LIMIT 6
        """,
        (current_user, current_user, current_user)
    ).fetchall()

    activities = [
        dict(activity)
        for group in (routine_activity, dsa_activity, challenge_activity, connection_activity)
        for activity in group
    ]
    for activity in activities:
        activity["created_at"] = normalize_activity_time(activity.get("created_at"))

    activities = sorted(
        activities,
        key=lambda activity: activity["created_at"],
        reverse=True
    )[:10]

    active_challenges = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM challenges
        WHERE status = 'active'
        AND (challenger_id=? OR challenged_id=?)
        """,
        (current_user, current_user)
    ).fetchone()["total"]

    conn.close()

    friends = [dict(friend) for friend in friends]
    for friend in friends:
        friend["streak"] = calculate_streak(friend["id"])

    return render_template(

        "friends/friends_hub.html",

        current_user=current_user_row,
        developer_users=developer_users,
        search_query=search_query,
        search_result=search_result,
        search_notice=search_notice,
        friends=friends,
        requests=requests,
        activities=activities,
        active_challenges=active_challenges,
        current_streak=calculate_streak(current_user)
    )


# =========================================
# SEND REQUEST
# =========================================

@app.route("/send-request/<int:user_id>", methods=["POST"])
def send_request(user_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    target = conn.execute(
        "SELECT id FROM users WHERE id=? AND id!=?",
        (user_id, session["user_id"])
    ).fetchone()

    existing_friend = conn.execute("""
        SELECT 1 FROM friends
        WHERE (user1_id=? AND user2_id=?) OR (user1_id=? AND user2_id=?)
    """, (session["user_id"], user_id, user_id, session["user_id"])).fetchone()

    existing = conn.execute("""

        SELECT *
        FROM friend_requests

        WHERE
        (
            (sender_id = ? AND receiver_id = ?)
            OR (sender_id = ? AND receiver_id = ?)
        )

    """, (

        session["user_id"],
        user_id,
        user_id,
        session["user_id"]

    )).fetchone()

    if target and not existing and not existing_friend:

        conn.execute("""

            INSERT INTO friend_requests (

                sender_id,
                receiver_id,
                status

            )

            VALUES (?, ?, ?)

        """, (

            session["user_id"],
            user_id,
            "pending"

        ))

        conn.commit()

    conn.close()

    return redirect("/friends-hub")


# =========================================
# ACCEPT REQUEST
# =========================================

@app.route("/accept-request/<int:request_id>", methods=["POST"])
def accept_request(request_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()
    try:
        request_data = conn.execute("""

            SELECT *
            FROM friend_requests

            WHERE id = ?
            AND receiver_id = ?
            AND status = 'pending'

        """, (request_id, session["user_id"])).fetchone()

        if request_data:

            conn.execute("""

                INSERT INTO friends (

                    user1_id,
                    user2_id

                )

                SELECT ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM friends
                    WHERE (user1_id=? AND user2_id=?)
                       OR (user1_id=? AND user2_id=?)
                )

            """, (

                request_data["sender_id"],
                request_data["receiver_id"],
                request_data["sender_id"],
                request_data["receiver_id"],
                request_data["receiver_id"],
                request_data["sender_id"]

            ))

            conn.execute("""

                DELETE FROM friend_requests
                WHERE id = ?

            """, (request_id,))

            flash("Friend request accepted.", "success")
        else:
            flash("Friend request was already handled.", "error")
        conn.commit()
    except Exception:
        conn.rollback()
        flash("Unable to accept this friend request. Please try again.", "error")
        app.logger.exception("Failed to accept friend request %s", request_id)
    finally:
        conn.close()

    return redirect(url_for("friends_hub"))


# =========================================
# REJECT REQUEST
# =========================================

@app.route("/reject-request/<int:request_id>", methods=["POST"])
def reject_request(request_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    conn.execute(
        """
        DELETE FROM friend_requests
        WHERE id=?
        AND receiver_id=?
        AND status='pending'
        """,
        (request_id, session["user_id"])
    )
    conn.commit()
    conn.close()

    flash("Friend request rejected.", "success")
    return redirect("/friends-hub")


# =========================================
# REMOVE FRIEND
# =========================================

@app.route("/remove-friend/<int:friend_id>", methods=["POST"])
def remove_friend(friend_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    conn.execute("""

        DELETE FROM friends

        WHERE

        (
            user1_id = ?
            AND user2_id = ?
        )

        OR

        (
            user1_id = ?
            AND user2_id = ?
        )

    """, (

        session["user_id"],
        friend_id,

        friend_id,
        session["user_id"]

    ))

    conn.commit()

    conn.close()

    return redirect("/friends-hub")


def calculate_streak_from_conn(conn, user_id):

    streak = 0

    routine_count = conn.execute(
        "SELECT COUNT(*) AS total FROM routines WHERE user_id=?",
        (user_id,)
    ).fetchone()["total"]

    if not routine_count:
        return 0

    current_day = date.today()

    while True:

        day_str = current_day.isoformat()

        completed = conn.execute(
            """
            SELECT COALESCE(SUM(tl.completed), 0) AS total
            FROM task_logs tl
            JOIN routines r
                ON tl.routine_id = r.id
            WHERE r.user_id=?
            AND tl.log_date=?
            """,
            (
                user_id,
                day_str
            )
        ).fetchone()["total"]

        if completed < routine_count:
            break

        streak += 1

        current_day -= timedelta(days=1)

    return streak


def calculate_streak(user_id):

    conn = get_db_connection()

    streak = calculate_streak_from_conn(conn, user_id)

    conn.close()

    return streak
# =========================
# VIEW USER PROFILE
# =========================
@app.route("/profile/<int:user_id>")
def view_profile(user_id):
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id=?
        """,
        (user_id,)
    ).fetchone()

    if not user:

        conn.close()
        return "User not found"

    is_own_profile = session["user_id"] == user_id
    is_friend = conn.execute(
        """
        SELECT 1 FROM friends
        WHERE (user1_id=? AND user2_id=?) OR (user1_id=? AND user2_id=?)
        """,
        (session["user_id"], user_id, user_id, session["user_id"])
    ).fetchone() is not None

    if not is_own_profile and not is_friend:
        can_preview = (
            request.args.get("preview") == "1"
            and (
                session.get("last_profile_search_id") == user_id
                or user["is_developer"]
            )
        )
        if not can_preview:
            conn.close()
            flash("Search by exact User ID before viewing a limited profile.", "info")
            return redirect(url_for("friends_hub"))

        request_state = conn.execute(
            """
            SELECT sender_id, receiver_id, status
            FROM friend_requests
            WHERE status='pending'
            AND ((sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?))
            """,
            (session["user_id"], user_id, user_id, session["user_id"])
        ).fetchone()
        relationship = "available"
        if request_state and request_state["sender_id"] == session["user_id"]:
            relationship = "sent"
        elif request_state:
            relationship = "received"

        conn.close()
        return render_template(
            "friends/profile_preview.html",
            user=user,
            relationship=relationship
        )

    activities = conn.execute(
        """
        SELECT *
        FROM activities
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 10
        """,
        (user_id,)
    ).fetchall()

    total_friends = conn.execute(
        """
        SELECT COUNT(*) as total

        FROM friends

        WHERE
        user1_id=?
        OR
        user2_id=?
        """,
        (user_id, user_id)
    ).fetchone()

    routine_stats = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM routines WHERE user_id=?) AS total,
            COALESCE((
                SELECT SUM(task_logs.completed)
                FROM task_logs
                JOIN routines ON routines.id=task_logs.routine_id
                WHERE routines.user_id=?
            ), 0) AS completed
        """,
        (user_id, user_id)
    ).fetchone()

    dsa_stats = conn.execute(
        """
        SELECT
            COUNT(*) AS topics,
            COALESCE(SUM(completed), 0) AS completed,
            COALESCE(SUM(target), 0) AS target
        FROM dsa_topics
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchone()

    challenge_stats = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN winner_id=? THEN 1 ELSE 0 END), 0) AS wins
        FROM challenges
        WHERE challenger_id=? OR challenged_id=?
        """,
        (user_id, user_id, user_id)
    ).fetchone()

    latest_topics = conn.execute(
        """
        SELECT topic_name, completed, target
        FROM dsa_topics
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 4
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    routine_total = routine_stats["total"]
    routine_completed = routine_stats["completed"]
    routine_progress = (
        round((routine_completed / routine_total) * 100)
        if routine_total else 0
    )

    dsa_target = dsa_stats["target"]
    dsa_progress = (
        min(round((dsa_stats["completed"] / dsa_target) * 100), 100)
        if dsa_target else 0
    )

    social_links = {
        "github": user["github"] if user["github"] and user["github"].startswith(("http://", "https://")) else None,
        "linkedin": user["linkedin"] if user["linkedin"] and user["linkedin"].startswith(("http://", "https://")) else None,
        "leetcode": user["leetcode"] if user["leetcode"] and user["leetcode"].startswith(("http://", "https://")) else None
    }

    return render_template(
        "friends/profile_view.html",
        user=user,
        activities=activities,
        total_friends=total_friends["total"],
        routine_stats=routine_stats,
        routine_progress=routine_progress,
        dsa_stats=dsa_stats,
        dsa_progress=dsa_progress,
        challenge_stats=challenge_stats,
        latest_topics=latest_topics,
        streak=calculate_streak(user_id),
        social_links=social_links,
        is_own_profile=is_own_profile,
        is_friend=is_friend
    )

#CHALLENGE FRIEND

@app.route("/challenge/<int:friend_id>", methods=["GET", "POST"])
def challenge_friend(friend_id):
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    current_user = session["user_id"]

    friendship = conn.execute(
        """
        SELECT 1 FROM friends
        WHERE (user1_id=? AND user2_id=?) OR (user1_id=? AND user2_id=?)
        """,
        (current_user, friend_id, friend_id, current_user)
    ).fetchone()

    if not friendship or current_user == friend_id:
        conn.close()
        return "Challenges are available between friends only", 403

    friend = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id=?
        """,
        (friend_id,)
    ).fetchone()

    if not friend:

        conn.close()
        return "Friend not found"

    challenge = conn.execute(
        """
        SELECT *
        FROM challenges
        WHERE
        (
            challenger_id=?
            AND challenged_id=?
        )
        OR
        (
            challenger_id=?
            AND challenged_id=?
        )
        ORDER BY id DESC
        LIMIT 1
        """,
        (
            current_user,
            friend_id,
            friend_id,
            current_user
        )
    ).fetchone()

    if request.method == "POST":
        if not challenge or challenge["status"] != "active":
            conn.execute(
                """
                INSERT INTO challenges
                (
                    challenger_id,
                    challenged_id,
                    status
                )
                VALUES (?,?,?)
                """,
                (
                    current_user,
                    friend_id,
                    "active"
                )
            )
            conn.commit()

        conn.close()
        return redirect(url_for("challenge_friend", friend_id=friend_id))

    current_profile = conn.execute(
        """
        SELECT
            users.*,
            COALESCE((SELECT SUM(completed) FROM dsa_topics WHERE user_id=users.id), 0) AS dsa_solved,
            COALESCE((SELECT SUM(target) FROM dsa_topics WHERE user_id=users.id), 0) AS dsa_target,
            COALESCE((
                SELECT SUM(task_logs.completed)
                FROM task_logs
                JOIN routines ON routines.id=task_logs.routine_id
                WHERE routines.user_id=users.id
            ), 0) AS habits_completed,
            COALESCE((SELECT COUNT(*) FROM routines WHERE user_id=users.id), 0) AS habits_total,
            COALESCE((SELECT COUNT(*) FROM challenges WHERE winner_id=users.id), 0) AS wins
        FROM users
        WHERE id=?
        """,
        (current_user,)
    ).fetchone()

    friend_profile = conn.execute(
        """
        SELECT
            users.*,
            COALESCE((SELECT SUM(completed) FROM dsa_topics WHERE user_id=users.id), 0) AS dsa_solved,
            COALESCE((SELECT SUM(target) FROM dsa_topics WHERE user_id=users.id), 0) AS dsa_target,
            COALESCE((
                SELECT SUM(task_logs.completed)
                FROM task_logs
                JOIN routines ON routines.id=task_logs.routine_id
                WHERE routines.user_id=users.id
            ), 0) AS habits_completed,
            COALESCE((SELECT COUNT(*) FROM routines WHERE user_id=users.id), 0) AS habits_total,
            COALESCE((SELECT COUNT(*) FROM challenges WHERE winner_id=users.id), 0) AS wins
        FROM users
        WHERE id=?
        """,
        (friend_id,)
    ).fetchone()

    recent_activity = conn.execute(
        """
        SELECT activities.*, users.username, users.profile_image
        FROM activities
        JOIN users ON users.id=activities.user_id
        WHERE activities.user_id IN (?, ?)
        ORDER BY activities.created_at DESC
        LIMIT 8
        """,
        (current_user, friend_id)
    ).fetchall()

    conn.close()

    current_profile = dict(current_profile)
    friend_profile = dict(friend_profile)
    current_profile["streak"] = calculate_streak(current_user)
    friend_profile["streak"] = calculate_streak(friend_id)

    for competitor in (current_profile, friend_profile):
        competitor["score"] = (
            competitor["dsa_solved"]
            + competitor["habits_completed"] * 5
            + competitor["streak"] * 3
        )

    if current_profile["score"] == friend_profile["score"]:
        leader = None
    elif current_profile["score"] > friend_profile["score"]:
        leader = current_profile["id"]
    else:
        leader = friend_profile["id"]

    return render_template(
        "friends/challenge_room.html",
        friend=friend_profile,
        current_user=current_profile,
        challenge=challenge,
        recent_activity=recent_activity,
        leader=leader
    )


@app.route("/friend-profile/<int:user_id>")
def friend_profile(user_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    friend = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id=?
        """,
        (user_id,)
    ).fetchone()

    total_tasks = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM routines
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchone()["total"]

    completed_tasks = conn.execute(
        """
        SELECT COALESCE(SUM(task_logs.completed), 0) AS total
        FROM task_logs
        JOIN routines ON routines.id=task_logs.routine_id
        WHERE routines.user_id=?
        """,
        (user_id,)
    ).fetchone()["total"]
    conn.close()

    if not friend:
        return "User not found"

    return render_template(
        "friends/friend_profile.html",
        friend=friend,
        total_tasks=total_tasks,
        completed_tasks=completed_tasks
    )

def fetch_leetcode_data(username):

    url = "https://leetcode.com/graphql"

    query = """
    query userProfile($username: String!) {

      matchedUser(username: $username) {

        submitStats {
          acSubmissionNum {
            difficulty
            count
          }
        }

        tagProblemCounts {
          advanced {
            tagName
            problemsSolved
          }

          intermediate {
            tagName
            problemsSolved
          }

          fundamental {
            tagName
            problemsSolved
          }
        }

        profile {
          ranking
          reputation
        }
      }
    }
    """

    variables = {
        "username": username
    }

    response = requests.post(

        url,

        json={
            "query": query,
            "variables": variables
        }
    )

    return response.json()

@app.route("/dsa_tracker")
def dsa_tracker():

    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]

    conn = get_db_connection()

    # -------------------------
    # DEFAULT VALUES
    # -------------------------

    leetcode_data = None

    topic_analytics = []

    weak_topics = []

    easy_count = 0
    medium_count = 0
    hard_count = 0
    total_solved = 0

    streak = 0

    weekly_labels = []
    weekly_counts = []

    # -------------------------
    # FETCH PROFILE
    # -------------------------

    profile = conn.execute(
        """
        SELECT *
        FROM dsa_profiles
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchone()

    # -------------------------
    # FETCH LEETCODE DATA
    # -------------------------

    if profile and profile["leetcode_username"]:

        username = profile["leetcode_username"]
        query = """
        query userPublicProfile($username: String!) {

            matchedUser(username: $username) {

                username

                profile {
                    ranking
                    reputation
                }

                submitStats {
                    acSubmissionNum {
                        difficulty
                        count
                    }
                }

                tagProblemCounts {

                    advanced {
                        tagName
                        problemsSolved
                    }

                    intermediate {
                        tagName
                        problemsSolved
                    }

                    fundamental {
                        tagName
                        problemsSolved
                    }
                }

                badges {
                    name
                }
            }
        }
        """

        
        try:

            response = requests.post(
                "https://leetcode.com/graphql",
                json={
                    "query": query,
                    "variables": {
                        "username": username
                    }
                },
                timeout=15
            )

            print("STATUS:", response.status_code)

            if response.status_code == 200:
                leetcode_data = response.json()

        except Exception as e:

            print("LEETCODE ERROR:", e)

            leetcode_data = None


    # -------------------------
    # PROCESS DATA
    # -------------------------

    if (
        leetcode_data
        and leetcode_data.get("data")
        and leetcode_data["data"].get("matchedUser")
    ):

        user_data = (
            leetcode_data["data"]["matchedUser"]
        )

        # ---------------------
        # DIFFICULTY STATS
        # ---------------------

        stats = user_data["submitStats"]["acSubmissionNum"]

        difficulty_map = {
            item["difficulty"]: item["count"]
            for item in stats
        }

        easy_count = difficulty_map.get("Easy", 0)

        medium_count = difficulty_map.get("Medium", 0)

        hard_count = difficulty_map.get("Hard", 0)

        total_solved = (
            easy_count
            + medium_count
            + hard_count
        )

        # ---------------------
        # SAVE DAILY HISTORY
        # ---------------------

        today = date.today().isoformat()

        existing = conn.execute(
            """
            SELECT *
            FROM dsa_history
            WHERE user_id=?
            AND log_date=?
            """,
            (
                user_id,
                today
            )
        ).fetchone()

        if existing:

            conn.execute(
                """
                UPDATE dsa_history
                SET solved_count=?
                WHERE id=?
                """,
                (
                    total_solved,
                    existing["id"]
                )
            )

        else:

            conn.execute(
                """
                INSERT INTO dsa_history(
                    user_id,
                    solved_count,
                    log_date
                )
                VALUES(?,?,?)
                """,
                (
                    user_id,
                    total_solved,
                    today
                )
            )

        # ---------------------
        # TOPIC ANALYTICS
        # ---------------------

        tag_data = user_data.get(
            "tagProblemCounts",
            {}
        )

        advanced = tag_data.get(
            "advanced",
            []
        )

        intermediate = tag_data.get(
            "intermediate",
            []
        )

        fundamental = tag_data.get(
            "fundamental",
            []
        )

        all_topics = (
            advanced
            + intermediate
            + fundamental
        )

        all_topics = sorted(
            all_topics,
            key=lambda x: x["problemsSolved"],
            reverse=True
        )

        topic_analytics = all_topics[:8]

        weak_topics = [
            topic
            for topic in all_topics
            if topic["problemsSolved"] < 5
        ][:5]

        conn.commit()

    # -------------------------
    # LOCAL DATABASE DATA
    # -------------------------

    topics = conn.execute(
        """
        SELECT *
        FROM dsa_topics
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchall()

    pending_topics = conn.execute(
        """
        SELECT *
        FROM pending_topics
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchall()

    history = conn.execute(
        """
        SELECT *
        FROM dsa_history
        WHERE user_id=?
        ORDER BY log_date
        """,
        (user_id,)
    ).fetchall()

    local_completed = sum(max(int(topic["completed"] or 0), 0) for topic in topics)
    local_target = sum(max(int(topic["target"] or 0), 0) for topic in topics)
    roadmap_progress = min(round((local_completed / local_target) * 100), 100) if local_target else 0
    mastered_topics = sum(
        1 for topic in topics
        if int(topic["target"] or 0) > 0
        and int(topic["completed"] or 0) >= int(topic["target"])
    )

    next_topic = None
    if topics:
        next_topic = min(
            topics,
            key=lambda topic: (
                int(topic["completed"] or 0) / int(topic["target"] or 1)
                if int(topic["target"] or 0) > 0 else 1
            )
        )

    history_changes = {}
    previous_total = None
    for row in history:
        current_total = int(row["solved_count"] or 0)
        history_changes[row["log_date"]] = (
            max(current_total - previous_total, 0)
            if previous_total is not None else 0
        )
        previous_total = current_total

    if not total_solved and history:
        total_solved = int(history[-1]["solved_count"] or 0)

    weekly_labels = []
    weekly_counts = []
    for offset in range(6, -1, -1):
        current_date = date.today() - timedelta(days=offset)
        weekly_labels.append(current_date.strftime("%a"))
        weekly_counts.append(history_changes.get(current_date.isoformat(), 0))

    streak = 0
    streak_date = date.today()
    while history_changes.get(streak_date.isoformat(), 0) > 0:
        streak += 1
        streak_date -= timedelta(days=1)

    daily_solved = history_changes.get(date.today().isoformat(), 0)
    latest_sync = history[-1]["log_date"] if history else None
    sync_available = bool(
        leetcode_data
        and leetcode_data.get("data")
        and leetcode_data["data"].get("matchedUser")
    )

    conn.close()

    return render_template(
        "dashboard/dsa_tracker.html",
        profile=profile,
        leetcode_data=leetcode_data,
        topics=topics,
        pending_topics=pending_topics,
        history=history,
        weekly_labels=weekly_labels,
        weekly_counts=weekly_counts,
        easy_count=easy_count,
        medium_count=medium_count,
        hard_count=hard_count,
        total_solved=total_solved,
        streak=streak,
        topic_analytics=topic_analytics,
        weak_topics=weak_topics,
        roadmap_progress=roadmap_progress,
        local_completed=local_completed,
        local_target=local_target,
        mastered_topics=mastered_topics,
        next_topic=next_topic,
        daily_solved=daily_solved,
        latest_sync=latest_sync,
        sync_available=sync_available
    )



@app.route(
    "/add_dsa_topic",
    methods=["POST"]
)
def add_dsa_topic():

    if "user_id" not in session:

        return redirect("/login")

    user_id = session["user_id"]

    topic_name = request.form.get("topic_name", "").strip()[:80]
    try:
        completed = max(int(request.form.get("completed", 0)), 0)
        target = max(int(request.form.get("target", 1)), 1)
    except ValueError:
        return "Solved and target values must be numbers", 400

    if not topic_name:
        return "Topic name is required", 400

    conn = get_db_connection()

    existing = conn.execute(
        "SELECT 1 FROM dsa_topics WHERE user_id=? AND LOWER(topic_name)=LOWER(?)",
        (user_id, topic_name)
    ).fetchone()

    if not existing:
        conn.execute(
        """
        INSERT INTO dsa_topics(
            user_id,
            topic_name,
            completed,
            target
        )
        VALUES(?,?,?,?)
        """,
        (
            user_id,
            topic_name,
            completed,
            target
        )
        )

    conn.commit()

    conn.close()

    return redirect("/dsa_tracker")

@app.route(
    "/add_pending_topic",
    methods=["POST"]
)
def add_pending_topic():

    if "user_id" not in session:

        return redirect("/login")

    user_id = session["user_id"]

    topic_name = request.form.get("topic_name", "").strip()[:80]

    if not topic_name:
        return "Topic name is required", 400

    conn = get_db_connection()

    existing = conn.execute(
        "SELECT 1 FROM pending_topics WHERE user_id=? AND LOWER(topic_name)=LOWER(?)",
        (user_id, topic_name)
    ).fetchone()

    if not existing:
        conn.execute(
        """
        INSERT INTO pending_topics(
            user_id,
            topic_name
        )
        VALUES(?,?)
        """,
        (
            user_id,
            topic_name
        )
        )

    conn.commit()

    conn.close()

    return redirect("/dsa_tracker")

@app.route(
    "/save_leetcode",
    methods=["POST"]
    )
def save_leetcode():


    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]

    username = request.form[
        "leetcode_username"
    ].strip()

    # Convert profile URL -> username
    if "leetcode.com" in username:
        username = (
            username
            .rstrip("/")
            .split("/")[-1]
        )

    # -------------------------
    # VALIDATE USERNAME
    # -------------------------

    validation_query = """
    query($username:String!){
        matchedUser(username:$username){
            username
        }
    }
    """

    try:

        response = requests.post(
            "https://leetcode.com/graphql",
            json={
                "query": validation_query,
                "variables": {
                    "username": username
                }
            },
            timeout=10
        )

        data = response.json()

        if (
            not data.get("data")
            or not data["data"].get("matchedUser")
        ):
            return "Invalid LeetCode Username"

    except Exception as e:

        print(
            "LEETCODE VALIDATION ERROR:",
            e
        )

        return "Unable to verify LeetCode username"

    # -------------------------
    # SAVE USERNAME
    # -------------------------

    conn = get_db_connection()

    existing = conn.execute(
        """
        SELECT *
        FROM dsa_profiles
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchone()

    if existing:

        conn.execute(
            """
            UPDATE dsa_profiles
            SET leetcode_username=?
            WHERE user_id=?
            """,
            (
                username,
                user_id
            )
        )

    else:

        conn.execute(
            """
            INSERT INTO dsa_profiles(
                user_id,
                leetcode_username
            )
            VALUES(?,?)
            """,
            (
                user_id,
                username
            )
        )

    conn.commit()
    conn.close()

    print(
        "VALID LEETCODE USER:",
        username
    )

    return redirect("/dsa_tracker")
    
@app.route("/export_habits")
def export_habits():

    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]

    conn = get_db_connection()

    routines = conn.execute(
        """
        SELECT id, task_name
        FROM routines
        WHERE user_id=?
        ORDER BY id
        """,
        (user_id,)
    ).fetchall()

    logs = conn.execute(
        """
        SELECT
            t.log_date,
            t.completed,
            r.task_name
        FROM task_logs t
        JOIN routines r
            ON t.routine_id = r.id
        WHERE r.user_id=?
        ORDER BY t.log_date
        """,
        (user_id,)
    ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)

    task_names = [
        routine["task_name"]
        for routine in routines
    ]

    dates = sorted(
        {
            log["log_date"]
            for log in logs
        }
    )

    habit_data = {}

    for date in dates:

        habit_data[date] = {
            task: "Incomplete"
            for task in task_names
        }

    for log in logs:

        habit_data[
            log["log_date"]
        ][
            log["task_name"]
        ] = (
            "Completed"
            if log["completed"]
            else "Incomplete"
        )

    writer.writerow(
        ["Date"] + task_names
    )

    for date in dates:

        row = [date]

        for task in task_names:

            row.append(
                habit_data[date][task]
            )

        writer.writerow(row)

    conn.close()

    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
            "attachment; filename=habit_history.csv"
        }
    )

@app.route("/export_dsa")
def export_dsa():

    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]

    conn = get_db_connection()

    history = conn.execute(
        """
        SELECT
            log_date,
            solved_count
        FROM dsa_history
        WHERE user_id=?
        ORDER BY log_date
        """,
        (user_id,)
    ).fetchall()

    output = io.StringIO()

    writer = csv.writer(output)

    writer.writerow([
        "Date",
        "Solved Problems"
    ])

    for row in history:

        writer.writerow([
            row["log_date"],
            row["solved_count"]
        ])

    conn.close()

    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
            "attachment; filename=dsa_progress.csv"
        }
    )

@app.route("/delete_dsa_topic/<int:id>", methods=["POST"])
def delete_dsa_topic(id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    conn.execute(
        """
        DELETE FROM dsa_topics
        WHERE id = ? AND user_id = ?
        """,
        (id, session["user_id"])
    )

    conn.commit()

    conn.close()

    return redirect("/dsa_tracker")

@app.route(
    "/update_dsa_topic/<int:id>",
    methods=["POST"]
)
def update_dsa_topic(id):

    if "user_id" not in session:
        return redirect("/login")

    try:
        completed = max(int(request.form.get("completed", 0)), 0)
        target = max(int(request.form.get("target", 1)), 1)
    except ValueError:
        return "Solved and target values must be numbers", 400

    conn = get_db_connection()

    conn.execute(
        """
        UPDATE dsa_topics
        SET completed = ?,
            target = ?
        WHERE id = ? AND user_id = ?
        """,
        (
            completed,
            target,
            id,
            session["user_id"]
        )
    )

    conn.commit()

    conn.close()

    return redirect("/dsa_tracker")

@app.route("/delete_pending_topic/<int:id>", methods=["POST"])
def delete_pending_topic(id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    conn.execute(
        "DELETE FROM pending_topics WHERE id=? AND user_id=?",
        (id, session["user_id"])
    )

    conn.commit()

    conn.close()

    return redirect("/dsa_tracker")


# if __name__ == "__main__":

#     app.run(
#         debug=True
#     )
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=os.environ.get("APP_ENV") != "production")
