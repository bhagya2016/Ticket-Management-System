from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
import sqlite3
from datetime import datetime
from werkzeug.utils import secure_filename
from pathlib import Path
import os

app = Flask(__name__)
app.secret_key = "change_this_secret_key"

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "database.db"
UPLOAD_FOLDER = BASE_DIR / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf", "txt", "docx"}
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_code TEXT UNIQUE,
            customer_name TEXT NOT NULL,
            customer_email TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT DEFAULT 'General',
            priority TEXT DEFAULT 'Low',
            status TEXT DEFAULT 'Open',
            assigned_engineer TEXT DEFAULT 'Not Assigned',
            progress TEXT DEFAULT 'Ticket submitted',
            attachment TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    users = [
        ("Admin User", "admin@ticketpro.com", "admin123", "admin"),
        ("Support Engineer", "engineer@ticketpro.com", "engineer123", "engineer")
    ]

    for user in users:
        conn.execute("""
            INSERT OR IGNORE INTO users (name, email, password, role)
            VALUES (?, ?, ?, ?)
        """, user)

    conn.commit()
    conn.close()


@app.route("/")
def home():
    return redirect(url_for("customer_portal"))


@app.route("/customer")
def customer_portal():
    return render_template("customer.html")


@app.route("/create-ticket", methods=["POST"])
def create_ticket():
    customer_name = request.form["customer_name"]
    customer_email = request.form["customer_email"]
    title = request.form["title"]
    description = request.form["description"]
    category = request.form["category"]

    filename = None
    file = request.files.get("attachment")

    if file and file.filename:
        if allowed_file(file.filename):
            filename = datetime.now().strftime("%Y%m%d%H%M%S_") + secure_filename(file.filename)
            file.save(UPLOAD_FOLDER / filename)
        else:
            flash("Invalid attachment type.")
            return redirect(url_for("customer_portal"))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = db()
    cursor = conn.execute("""
        INSERT INTO tickets 
        (customer_name, customer_email, title, description, category, attachment, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (customer_name, customer_email, title, description, category, filename, now, now))

    ticket_id = cursor.lastrowid
    ticket_code = f"TKT-{1000 + ticket_id}"

    conn.execute("UPDATE tickets SET ticket_code=? WHERE id=?", (ticket_code, ticket_id))
    conn.commit()
    conn.close()

    flash(f"Ticket created successfully! Your Ticket ID is {ticket_code}")
    return redirect(url_for("customer_portal"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = db()
        user = conn.execute(
            "SELECT * FROM users WHERE email=? AND password=?",
            (email, password)
        ).fetchone()
        conn.close()

        if user:
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            flash("Login successful.")
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.")
    return redirect(url_for("login"))


def login_required():
    return "user_id" in session


@app.route("/dashboard")
def dashboard():
    if not login_required():
        return redirect(url_for("login"))

    conn = db()

    stats = {
        "total": conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0],
        "open": conn.execute("SELECT COUNT(*) FROM tickets WHERE status='Open'").fetchone()[0],
        "progress": conn.execute("SELECT COUNT(*) FROM tickets WHERE status='In Progress'").fetchone()[0],
        "resolved": conn.execute("SELECT COUNT(*) FROM tickets WHERE status='Resolved'").fetchone()[0],
        "closed": conn.execute("SELECT COUNT(*) FROM tickets WHERE status='Closed'").fetchone()[0],
        "critical": conn.execute("SELECT COUNT(*) FROM tickets WHERE priority='Critical'").fetchone()[0],
    }

    status_rows = conn.execute("""
        SELECT status, COUNT(*) AS count 
        FROM tickets 
        GROUP BY status
    """).fetchall()

    priority_rows = conn.execute("""
        SELECT priority, COUNT(*) AS count 
        FROM tickets 
        GROUP BY priority
    """).fetchall()

    recent_tickets = conn.execute("""
        SELECT * FROM tickets 
        ORDER BY id DESC 
        LIMIT 5
    """).fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        stats=stats,
        status_rows=status_rows,
        priority_rows=priority_rows,
        recent_tickets=recent_tickets
    )


@app.route("/tickets")
def tickets():
    if not login_required():
        return redirect(url_for("login"))

    search = request.args.get("search", "")
    status = request.args.get("status", "")
    priority = request.args.get("priority", "")
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")

    query = "SELECT * FROM tickets WHERE 1=1"
    params = []

    if search:
        query += """ AND (
            ticket_code LIKE ? OR customer_name LIKE ? OR customer_email LIKE ? OR title LIKE ?
        )"""
        params.extend([f"%{search}%"] * 4)

    if status:
        query += " AND status=?"
        params.append(status)

    if priority:
        query += " AND priority=?"
        params.append(priority)

    if start_date:
        query += " AND date(created_at) >= date(?)"
        params.append(start_date)

    if end_date:
        query += " AND date(created_at) <= date(?)"
        params.append(end_date)

    query += " ORDER BY id DESC"

    conn = db()
    all_tickets = conn.execute(query, params).fetchall()
    conn.close()

    return render_template(
        "tickets.html",
        tickets=all_tickets,
        search=search,
        status=status,
        priority=priority,
        start_date=start_date,
        end_date=end_date
    )


@app.route("/ticket/<int:id>", methods=["GET", "POST"])
def ticket_detail(id):
    if not login_required():
        return redirect(url_for("login"))

    conn = db()
    ticket = conn.execute("SELECT * FROM tickets WHERE id=?", (id,)).fetchone()

    if request.method == "POST":
        priority = request.form["priority"]
        status = request.form["status"]
        assigned_engineer = request.form["assigned_engineer"]
        progress = request.form["progress"]
        updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn.execute("""
            UPDATE tickets
            SET priority=?, status=?, assigned_engineer=?, progress=?, updated_at=?
            WHERE id=?
        """, (priority, status, assigned_engineer, progress, updated_at, id))

        conn.commit()
        conn.close()

        flash("Ticket updated successfully.")
        return redirect(url_for("tickets"))

    conn.close()
    return render_template("ticket_detail.html", ticket=ticket)


@app.route("/delete-ticket/<int:id>")
def delete_ticket(id):
    if not login_required():
        return redirect(url_for("login"))

    if session.get("role") != "admin":
        flash("Only admin can delete tickets.")
        return redirect(url_for("tickets"))

    conn = db()
    conn.execute("DELETE FROM tickets WHERE id=?", (id,))
    conn.commit()
    conn.close()

    flash("Ticket deleted successfully.")
    return redirect(url_for("tickets"))


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/analytics")
def analytics():
    if not login_required():
        return redirect(url_for("login"))

    conn = db()

    status_rows = conn.execute("""
        SELECT status, COUNT(*) AS count 
        FROM tickets 
        GROUP BY status
    """).fetchall()

    priority_rows = conn.execute("""
        SELECT priority, COUNT(*) AS count 
        FROM tickets 
        GROUP BY priority
    """).fetchall()

    daily_rows = conn.execute("""
        SELECT date(created_at) AS day, COUNT(*) AS count
        FROM tickets
        GROUP BY date(created_at)
        ORDER BY day
        LIMIT 10
    """).fetchall()

    conn.close()

    return render_template(
        "analytics.html",
        status_rows=status_rows,
        priority_rows=priority_rows,
        daily_rows=daily_rows
    )


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
