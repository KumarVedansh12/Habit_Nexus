from flask import Flask, render_template, request, redirect
from database import get_db_connection

app = Flask(__name__)

@app.route("/")
def home():
    return redirect("/dashboard")


@app.route("/dashboard")
def dashboard():

    conn = get_db_connection()

    routines = conn.execute(
        "SELECT * FROM routines"
    ).fetchall()

    total = len(routines)

    completed = sum(
        routine["completed"]
        for routine in routines
    )
    streak = 0
    progress = 0

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
    streak=streak
)


@app.route("/add_routine", methods=["POST"])
def add_routine():

    task = request.form["task"]

    if task.strip():

        conn = get_db_connection()

        conn.execute(
            "INSERT INTO routines (user_id, task_name) VALUES (?, ?)",
            (1, task)
        )

        conn.commit()
        conn.close()

    return redirect("/dashboard")
@app.route("/toggle/<int:id>")
def toggle_task(id):

    conn = get_db_connection()

    routine = conn.execute(
        "SELECT completed FROM routines WHERE id=?",
        (id,)
    ).fetchone()

    new_value = 0 if routine["completed"] else 1

    conn.execute(
        "UPDATE routines SET completed=? WHERE id=?",
        (new_value, id)
    )

    conn.commit()
    conn.close()

    return redirect("/dashboard")

@app.route("/delete/<int:id>")
def delete_task(id):

    conn = get_db_connection()

    conn.execute(
        "DELETE FROM routines WHERE id=?",
        (id,)
    )

    conn.commit()
    conn.close()

    return redirect("/dashboard")

if __name__ == "__main__":
    app.run(debug=True)