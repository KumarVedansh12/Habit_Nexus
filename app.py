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

if __name__ == "__main__":
    app.run(debug=True)