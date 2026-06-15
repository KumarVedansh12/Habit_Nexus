from flask import Flask, render_template, request, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db_connection, init_db
from datetime import date
from datetime import date, timedelta
import csv
from flask import Response

app = Flask(__name__)
app.secret_key = "routinebattle123"

init_db()
@app.route("/")
def home():
    return redirect("/dashboard")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    selected_date = request.args.get(
    "date",
    date.today().isoformat()
)

    routines = conn.execute(
        """
        SELECT
            r.id,
            r.task_name,
            COALESCE(t.completed, 0) as completed

        FROM routines r

        LEFT JOIN task_logs t
        ON r.id = t.routine_id
        AND t.log_date = ?

        WHERE r.user_id = ?
        """,
        (selected_date, session["user_id"])
    ).fetchall()
    total = len(routines)

    completed = sum(
        routine["completed"]
        for routine in routines
    )
    streak = calculate_streak(
    session["user_id"]
    )   
    progress = 0
    heatmap_data = get_heatmap_data(
    session["user_id"]
    )

    if total > 0:
        progress = round(
            (completed / total) * 100
        )

    conn.close()

    # return render_template(
    #     "dashboard.html",
    #     routines=routines,
    #     progress=progress
    # )

    return render_template(
    "dashboard.html",
    routines=routines,
    progress=progress,
    total=total,
    completed=completed,
    streak=streak,
    selected_date=selected_date,
    heatmap_data=heatmap_data
)



@app.route("/add_routine", methods=["POST"])
def add_routine():

    task = request.form["task"]

    if task.strip():

        conn = get_db_connection()

        conn.execute(
            "INSERT INTO routines (user_id, task_name) VALUES (?, ?)",
            (session["user_id"], task)
        )

        conn.commit()
        conn.close()

    return redirect("/dashboard")
@app.route("/toggle/<int:id>")
def toggle(id):

    if "user_id" not in session:
        return redirect("/login")

    selected_date = request.args.get(
    "date",
    date.today().isoformat()
)

    conn = get_db_connection()

    log = conn.execute(
        """
        SELECT *
        FROM task_logs
        WHERE routine_id=?
        AND log_date=?
        """,
        # (id, today)
        (id, selected_date)
    ).fetchone()

    if log:

        new_status = 1

        if log["completed"] == 1:
            new_status = 0

        conn.execute(
            """
            UPDATE task_logs
            SET completed=?
            WHERE id=?
            """,
            (new_status, log["id"])
        )

    else:

        conn.execute(
            """
            INSERT INTO task_logs
            (routine_id, log_date, completed)
            VALUES (?, ?, 1)
            """,
            # (id, today)
            (id, selected_date)
        )

    conn.commit()
    conn.close()

    return redirect("/dashboard")

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]

        hashed_password = generate_password_hash(password)

        conn = get_db_connection()

        conn.execute(
            """
            INSERT INTO users
            (username,email,password)
            VALUES (?,?,?)
            """,
            (username,email,hashed_password)
        )

        conn.commit()
        conn.close()

        return redirect("/login")

    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():

    if request.method == "POST":

        # email = request.form["email"]
        # password = request.form["password"]

        # conn = get_db_connection()

        # user = conn.execute(
        #     "SELECT * FROM users WHERE email=?",
        #     (email,)
        # ).fetchone()

        identifier = request.form["identifier"]
        password = request.form["password"]

        conn = get_db_connection()

        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE username = ?
            OR email = ?
            """,
            (identifier, identifier)
        ).fetchone()
        
        conn.close()

        if user and check_password_hash(
            user["password"],
            password
        ):

            session["user_id"] = user["id"]

            return redirect("/dashboard")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/settings", methods=["GET", "POST"])
def settings():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    user = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (session["user_id"],)
    ).fetchone()

    if request.method == "POST":

        username = request.form["username"]
        email = request.form["email"]

        conn.execute(
            """
            UPDATE users
            SET username=?,
                email=?
            WHERE id=?
            """,
            (username, email, session["user_id"])
        )

        conn.commit()

        return redirect("/dashboard")

    conn.close()

    return render_template(
        "settings.html",
        user=user
    )

@app.route("/change-password", methods=["POST"])
def change_password():

    if "user_id" not in session:
        return redirect("/login")

    current_password = request.form["current_password"]
    new_password = request.form["new_password"]

    conn = get_db_connection()

    user = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (session["user_id"],)
    ).fetchone()

    if not check_password_hash(
        user["password"],
        current_password
    ):
        conn.close()
        return "Current password is incorrect"

    hashed_password = generate_password_hash(
        new_password
    )

    conn.execute(
        """
        UPDATE users
        SET password=?
        WHERE id=?
        """,
        (
            hashed_password,
            session["user_id"]
        )
    )

    conn.commit()
    conn.close()

    return redirect("/settings")

@app.route("/delete/<int:id>")
def delete(id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    conn.execute(
        """
        DELETE FROM routines
        WHERE id=?
        AND user_id=?
        """,
        (id, session["user_id"])
    )

    conn.commit()
    conn.close()

    return redirect("/dashboard")

def calculate_streak(user_id):

    conn = get_db_connection()

    streak = 0

    current_day = date.today()

    while True:

        day_str = current_day.isoformat()

        logs = conn.execute(
            """
            SELECT tl.completed

            FROM task_logs tl

            JOIN routines r
            ON tl.routine_id = r.id

            WHERE r.user_id = ?
            AND tl.log_date = ?
            """,
            (user_id, day_str)
        ).fetchall()

        if not logs:
            break

        total = len(logs)

        completed = sum(
            log["completed"]
            for log in logs
        )

        if total == 0 or completed < total:
            break

        streak += 1

        current_day -= timedelta(days=1)

    conn.close()

    return streak

def get_heatmap_data(user_id):

    conn = get_db_connection()

    data = conn.execute(
        """
        SELECT
            log_date,
            COUNT(*) as total,
            SUM(tl.completed) as completed

        FROM task_logs tl

        JOIN routines r
        ON tl.routine_id = r.id

        WHERE r.user_id=?

        GROUP BY log_date
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    return data

@app.route("/export-csv")
def export_csv():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    data = conn.execute(
        """
        SELECT
            tl.log_date,
            r.task_name,
            tl.completed

        FROM task_logs tl

        JOIN routines r
        ON tl.routine_id = r.id

        WHERE r.user_id = ?

        ORDER BY tl.log_date DESC
        """,
        (session["user_id"],)
    ).fetchall()

    conn.close()

    def generate():

        yield "Date,Task,Completed\n"

        for row in data:

            status = "Yes" if row["completed"] else "No"

            yield f"{row['log_date']},{row['task_name']},{status}\n"

    return Response(
        generate(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
            "attachment; filename=routine_history.csv"
        }
    )

@app.route("/friends")
def friends():

    if "user_id" not in session:
        return redirect("/login")

    search = request.args.get("search", "")

    conn = get_db_connection()

    users = []

    if search:

        users = conn.execute(
            """
            SELECT id, username
            FROM users
            WHERE username LIKE ?
            AND id != ?
            """,
            (f"%{search}%", session["user_id"])
        ).fetchall()

    conn.close()

    return render_template(
        "friends.html",
        users=users,
        search=search
    )

@app.route("/send-request/<int:user_id>")
def send_request(user_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    conn.execute(
        """
        INSERT INTO friend_requests
        (sender_id, receiver_id)
        VALUES (?, ?)
        """,
        (session["user_id"], user_id)
    )

    conn.commit()
    conn.close()

    return redirect("/friends")

@app.route("/requests")
def requests_page():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    requests = conn.execute(
        """
        SELECT
            fr.id,
            u.username

        FROM friend_requests fr

        JOIN users u
        ON fr.sender_id = u.id

        WHERE fr.receiver_id = ?
        AND fr.status = 'pending'
        """,
        (session["user_id"],)
    ).fetchall()

    conn.close()

    return render_template(
        "requests.html",
        requests=requests
    )

@app.route("/accept-request/<int:req_id>")
def accept_request(req_id):

    conn = get_db_connection()

    request_data = conn.execute(
        """
        SELECT *
        FROM friend_requests
        WHERE id=?
        """,
        (req_id,)
    ).fetchone()

    sender = request_data["sender_id"]
    receiver = request_data["receiver_id"]

    conn.execute(
        """
        INSERT INTO friends
        (user_id, friend_id)
        VALUES (?, ?)
        """,
        (sender, receiver)
    )

    conn.execute(
        """
        INSERT INTO friends
        (user_id, friend_id)
        VALUES (?, ?)
        """,
        (receiver, sender)
    )

    conn.execute(
        """
        UPDATE friend_requests
        SET status='accepted'
        WHERE id=?
        """,
        (req_id,)
    )

    conn.commit()
    conn.close()

    return redirect("/requests")


def get_leaderboard():

    conn = get_db_connection()

    data = conn.execute(
        """
        SELECT
            u.username,
            COALESCE(
                SUM(tl.completed) * 10,
                0
            ) as points

        FROM users u

        LEFT JOIN routines r
        ON u.id = r.user_id

        LEFT JOIN task_logs tl
        ON r.id = tl.routine_id

        GROUP BY u.id

        ORDER BY points DESC
        """
    ).fetchall()

    conn.close()

    return data

@app.route("/leaderboard")
def leaderboard():

    data = get_leaderboard()

    return render_template(
        "leaderboard.html",
        users=data
)

@app.route("/reject-request/<int:req_id>")
def reject_request(req_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    conn.execute(
        """
        UPDATE friend_requests
        SET status='rejected'
        WHERE id=?
        """,
        (req_id,)
    )

    conn.commit()
    conn.close()

    return redirect("/requests")   

@app.route("/my-friends")
def my_friends():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    friends = conn.execute(
        """
        SELECT
            u.id,
            u.username

        FROM friends f

        JOIN users u
        ON f.friend_id = u.id

        WHERE f.user_id = ?
        """,
        (session["user_id"],)
    ).fetchall()

    conn.close()

    return render_template(
        "my_friends.html",
        friends=friends
    )  

@app.route("/remove-friend/<int:friend_id>")
def remove_friend(friend_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    conn.execute(
        """
        DELETE FROM friends
        WHERE user_id=?
        AND friend_id=?
        """,
        (session["user_id"], friend_id)
    )

    conn.execute(
        """
        DELETE FROM friends
        WHERE user_id=?
        AND friend_id=?
        """,
        (friend_id, session["user_id"])
    )

    conn.commit()
    conn.close()

    return redirect("/my-friends")

def get_user_progress(user_id):

    conn = get_db_connection()

    today = date.today().isoformat()

    stats = conn.execute(
        """
        SELECT
            COUNT(*) as total,
            COALESCE(
                SUM(tl.completed),
                0
            ) as completed

        FROM routines r

        LEFT JOIN task_logs tl
        ON r.id = tl.routine_id
        AND tl.log_date = ?

        WHERE r.user_id = ?
        """,
        (today, user_id)
    ).fetchone()

    conn.close()

    total = stats["total"]

    if total == 0:
        return 0

    return round(
        (stats["completed"] / total) * 100
    )

@app.route("/compare/<int:friend_id>")
def compare(friend_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()

    me = conn.execute(
        "SELECT username FROM users WHERE id=?",
        (session["user_id"],)
    ).fetchone()

    friend = conn.execute(
        "SELECT username FROM users WHERE id=?",
        (friend_id,)
    ).fetchone()

    conn.close()

    my_score = get_user_progress(
        session["user_id"]
    )

    friend_score = get_user_progress(
        friend_id
    )

    winner = "Tie"

    if my_score > friend_score:
        winner = me["username"]

    elif friend_score > my_score:
        winner = friend["username"]

    return render_template(
        "compare.html",
        me=me,
        friend=friend,
        my_score=my_score,
        friend_score=friend_score,
        winner=winner
    )

if __name__ == "__main__":
    app.run(debug=True)