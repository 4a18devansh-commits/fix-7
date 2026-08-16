"""
TeamPulse - Backend (app.py)
================================
Real Flask backend with three separate roles:
  - BOSS: signs up, logs in with email+password, manages employees, sees dashboard
  - EMPLOYEE: never signs up. Logs in with a username+password the boss created.
    Can only reach the screen-capture page - no dashboard access.
  - ADMIN (you, the site owner): logs in with admin/admin, sees every customer
    account and can edit their validity/expiry date.

All timestamps are stored and displayed in IST (Indian Standard Time).
"""

import os
import sqlite3
import hashlib
import socket
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, session, send_from_directory

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
SCREENSHOT_DIR = os.path.join(DATA_DIR, "screenshots")
DB_PATH = os.path.join(DATA_DIR, "teampulse.db")
FRONTEND_DIR = os.path.join(APP_DIR, "frontend")

os.makedirs(SCREENSHOT_DIR, exist_ok=True)

app = Flask(__name__, static_folder=FRONTEND_DIR)
app.secret_key = os.environ.get("SECRET_KEY", "teampulse-dev-secret-change-in-real-deployment")

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"

IST_OFFSET = timedelta(hours=5, minutes=30)


def now_ist():
    return datetime.utcnow() + IST_OFFSET


def today_ist_str():
    return now_ist().date().isoformat()


# ---------------- DATABASE ----------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, company TEXT, email TEXT UNIQUE,
        password_hash TEXT, employee_limit INTEGER,
        validity_date TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER,
        username TEXT UNIQUE,
        password_hash TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS settings (
        account_id INTEGER PRIMARY KEY,
        record_start TEXT DEFAULT '09:00',
        record_end TEXT DEFAULT '18:00',
        retention_days INTEGER DEFAULT 7,
        capture_interval_seconds INTEGER DEFAULT 15
    );
    CREATE TABLE IF NOT EXISTS recordings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER,
        employee_username TEXT,
        filepath TEXT,
        activity_score INTEGER,
        status TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS employee_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER,
        requested_limit INTEGER,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS capture_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER,
        employee_username TEXT,
        event_type TEXT,
        created_at TEXT
    );
    """)
    conn.commit()
    conn.close()


def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


def is_account_valid(account_row):
    if not account_row["validity_date"]:
        return True
    return today_ist_str() <= account_row["validity_date"]


# ---------------- BOSS AUTH ----------------
@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.json
    name, company, email = data.get("name"), data.get("company"), data.get("email")
    password, employees = data.get("password"), data.get("employees")
    if not all([name, company, email, password, employees]):
        return jsonify({"error": "Missing fields"}), 400

    conn = get_db()
    try:
        default_validity = (now_ist() + timedelta(days=30)).date().isoformat()
        cur = conn.execute(
            "INSERT INTO accounts (name, company, email, password_hash, employee_limit, validity_date, created_at) VALUES (?,?,?,?,?,?,?)",
            (name, company, email, hash_pw(password), int(employees), default_validity, now_ist().isoformat())
        )
        account_id = cur.lastrowid
        conn.execute("INSERT INTO settings (account_id) VALUES (?)", (account_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "An account with this email already exists"}), 400
    conn.close()
    session.clear()
    session["role"] = "boss"
    session["account_id"] = account_id
    return jsonify({"ok": True})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    email, password = data.get("email", "").strip(), data.get("password", "")

    if email == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session.clear()
        session["role"] = "admin"
        return jsonify({"ok": True, "role": "admin"})

    conn = get_db()
    row = conn.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "No account found with this email"}), 401
    if row["password_hash"] != hash_pw(password):
        return jsonify({"error": "Incorrect password"}), 401
    if not is_account_valid(row):
        return jsonify({"error": "Validity expired. Please contact the administrator."}), 403

    session.clear()
    session["role"] = "boss"
    session["account_id"] = row["id"]
    return jsonify({"ok": True, "role": "boss"})


# ---------------- EMPLOYEE AUTH ----------------
@app.route("/api/employee-login", methods=["POST"])
def employee_login():
    data = request.json
    username, password = data.get("username", "").strip(), data.get("password", "")

    conn = get_db()
    emp = conn.execute("SELECT * FROM employees WHERE username=?", (username,)).fetchone()
    if not emp:
        conn.close()
        return jsonify({"error": "Username not found"}), 401
    if emp["password_hash"] != hash_pw(password):
        conn.close()
        return jsonify({"error": "Incorrect password"}), 401

    account = conn.execute("SELECT * FROM accounts WHERE id=?", (emp["account_id"],)).fetchone()
    conn.close()
    if not account or not is_account_valid(account):
        return jsonify({"error": "Validity expired. Please contact the administrator."}), 403

    session.clear()
    session["role"] = "employee"
    session["account_id"] = emp["account_id"]
    session["employee_username"] = emp["username"]
    return jsonify({"ok": True, "role": "employee"})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
def me():
    role = session.get("role")
    if not role:
        return jsonify({"loggedIn": False})

    if role == "admin":
        return jsonify({"loggedIn": True, "role": "admin"})

    if role == "boss":
        conn = get_db()
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (session["account_id"],)).fetchone()
        conn.close()
        if not row:
            return jsonify({"loggedIn": False})
        return jsonify({
            "loggedIn": True, "role": "boss", "name": row["name"], "company": row["company"],
            "email": row["email"], "employee_limit": row["employee_limit"],
            "validity_date": row["validity_date"]
        })

    if role == "employee":
        conn = get_db()
        emp = conn.execute("SELECT * FROM employees WHERE account_id=? AND username=?",
                            (session["account_id"], session["employee_username"])).fetchone()
        if not emp:
            # Employee was removed by their boss since logging in - end their session
            conn.close()
            session.clear()
            return jsonify({"loggedIn": False, "removed": True})
        acct = conn.execute("SELECT * FROM accounts WHERE id=?", (session["account_id"],)).fetchone()
        conn.close()
        if not acct or not is_account_valid(acct):
            session.clear()
            return jsonify({"loggedIn": False})
        return jsonify({
            "loggedIn": True, "role": "employee",
            "username": session["employee_username"],
            "company": acct["company"] if acct else ""
        })

    return jsonify({"loggedIn": False})


# ---------------- EMPLOYEE MANAGEMENT (boss only) ----------------
@app.route("/api/employees", methods=["GET", "POST"])
def employees_route():
    if session.get("role") != "boss":
        return jsonify({"error": "Not authorized"}), 403
    account_id = session["account_id"]
    conn = get_db()

    if request.method == "POST":
        data = request.json
        username, password = data.get("username", "").strip(), data.get("password", "")
        if not username or not password:
            conn.close()
            return jsonify({"error": "Username and password required"}), 400

        current_count = conn.execute(
            "SELECT COUNT(*) as c FROM employees WHERE account_id=?", (account_id,)
        ).fetchone()["c"]
        acct = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if current_count >= acct["employee_limit"]:
            conn.close()
            return jsonify({"error": f"Employee limit reached ({acct['employee_limit']}). Increase it in your plan to add more."}), 400

        try:
            conn.execute(
                "INSERT INTO employees (account_id, username, password_hash, created_at) VALUES (?,?,?,?)",
                (account_id, username, hash_pw(password), now_ist().isoformat())
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({"error": "That username is already taken"}), 400
        conn.close()
        return jsonify({"ok": True})

    rows = conn.execute("""
        SELECT e.id, e.username, e.created_at, MAX(r.created_at) as last_seen
        FROM employees e LEFT JOIN recordings r ON e.username = r.employee_username AND e.account_id = r.account_id
        WHERE e.account_id=?
        GROUP BY e.id
        ORDER BY e.created_at
    """, (account_id,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/employees/<int:emp_id>", methods=["DELETE"])
def delete_employee(emp_id):
    if session.get("role") != "boss":
        return jsonify({"error": "Not authorized"}), 403
    conn = get_db()
    conn.execute("DELETE FROM employees WHERE id=? AND account_id=?", (emp_id, session["account_id"]))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ---------------- EMPLOYEE LIMIT REQUESTS (boss requests, admin approves) ----------------
@app.route("/api/employee-request", methods=["GET", "POST"])
def employee_request():
    if session.get("role") != "boss":
        return jsonify({"error": "Not authorized"}), 403
    conn = get_db()
    account_id = session["account_id"]

    if request.method == "POST":
        data = request.json
        requested_limit = int(data.get("requested_limit", 0))
        acct = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if requested_limit <= acct["employee_limit"]:
            conn.close()
            return jsonify({"error": "Requested number must be higher than your current limit"}), 400
        pending = conn.execute(
            "SELECT * FROM employee_requests WHERE account_id=? AND status='pending'", (account_id,)
        ).fetchone()
        if pending:
            conn.close()
            return jsonify({"error": "You already have a pending request. Please wait for it to be reviewed."}), 400
        conn.execute(
            "INSERT INTO employee_requests (account_id, requested_limit, status, created_at) VALUES (?,?,?,?)",
            (account_id, requested_limit, "pending", now_ist().isoformat())
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    row = conn.execute(
        "SELECT * FROM employee_requests WHERE account_id=? ORDER BY created_at DESC LIMIT 1", (account_id,)
    ).fetchone()
    conn.close()
    return jsonify(dict(row) if row else {})


# ---------------- SETTINGS (boss only) ----------------
@app.route("/api/settings", methods=["GET", "POST"])
def settings_route():
    if session.get("role") != "boss":
        return jsonify({"error": "Not authorized"}), 403
    conn = get_db()
    if request.method == "POST":
        data = request.json
        conn.execute(
            "UPDATE settings SET record_start=?, record_end=?, retention_days=?, capture_interval_seconds=? WHERE account_id=?",
            (data.get("record_start"), data.get("record_end"), int(data.get("retention_days")),
             int(data.get("capture_interval_seconds")), session["account_id"])
        )
        conn.commit()
    row = conn.execute("SELECT * FROM settings WHERE account_id=?", (session["account_id"],)).fetchone()
    conn.close()
    return jsonify(dict(row))


def within_recording_window(record_start, record_end):
    now = now_ist().strftime("%H:%M")
    if record_start <= record_end:
        return record_start <= now <= record_end
    return now >= record_start or now <= record_end


# ---------------- CAPTURE (employee only) ----------------
@app.route("/api/capture", methods=["POST"])
def capture():
    if session.get("role") != "employee":
        return jsonify({"error": "Not authorized"}), 403
    account_id = session["account_id"]
    employee_username = session["employee_username"]

    conn = get_db()

    # Guard against a removed employee or expired account still holding an old session
    emp = conn.execute("SELECT * FROM employees WHERE account_id=? AND username=?",
                        (account_id, employee_username)).fetchone()
    account = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not emp or not account or not is_account_valid(account):
        conn.close()
        session.clear()
        return jsonify({"error": "Session ended", "loggedOut": True}), 401

    settings_row = conn.execute("SELECT * FROM settings WHERE account_id=?", (account_id,)).fetchone()

    if not within_recording_window(settings_row["record_start"], settings_row["record_end"]):
        conn.close()
        return jsonify({"skipped": True, "reason": "Outside scheduled recording hours"}), 200

    activity_score = int(request.form.get("activity_score", 0))
    status = request.form.get("status", "active")
    image = request.files.get("image")

    account_folder = os.path.join(SCREENSHOT_DIR, str(account_id))
    os.makedirs(account_folder, exist_ok=True)

    filename = None
    if image:
        ts = now_ist().strftime("%Y%m%d_%H%M%S_%f")
        safe_name = "".join(c for c in employee_username if c.isalnum()) or "employee"
        filename = f"{safe_name}_{ts}.jpg"
        image.save(os.path.join(account_folder, filename))

    conn.execute(
        "INSERT INTO recordings (account_id, employee_username, filepath, activity_score, status, created_at) VALUES (?,?,?,?,?,?)",
        (account_id, employee_username, filename, activity_score, status, now_ist().isoformat())
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "saved": filename, "capture_interval_seconds": settings_row["capture_interval_seconds"]})


@app.route("/api/capture-interval")
def capture_interval():
    if session.get("role") != "employee":
        return jsonify({"error": "Not authorized"}), 403
    conn = get_db()
    row = conn.execute("SELECT capture_interval_seconds FROM settings WHERE account_id=?", (session["account_id"],)).fetchone()
    conn.close()
    return jsonify({"capture_interval_seconds": row["capture_interval_seconds"]})


@app.route("/api/capture-event", methods=["POST"])
def capture_event():
    if session.get("role") != "employee":
        return jsonify({"error": "Not authorized"}), 403
    data = request.json
    event_type = data.get("event_type")
    if event_type not in ("started", "stopped"):
        return jsonify({"error": "Invalid event type"}), 400
    conn = get_db()
    conn.execute(
        "INSERT INTO capture_events (account_id, employee_username, event_type, created_at) VALUES (?,?,?,?)",
        (session["account_id"], session["employee_username"], event_type, now_ist().isoformat())
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/events")
def get_events():
    if session.get("role") != "boss":
        return jsonify({"error": "Not authorized"}), 403
    since_id = int(request.args.get("since", 0))
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM capture_events WHERE account_id=? AND id > ? ORDER BY id ASC",
        (session["account_id"], since_id)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ---------------- LIVE DASHBOARD (boss only) ----------------
@app.route("/api/live")
def live():
    if session.get("role") != "boss":
        return jsonify({"error": "Not authorized"}), 403
    conn = get_db()
    rows = conn.execute("""
        SELECT employee_username, activity_score, status, MAX(created_at) as last_seen
        FROM recordings WHERE account_id=? GROUP BY employee_username
        ORDER BY last_seen DESC
    """, (session["account_id"],)).fetchall()
    conn.close()
    results = []
    for r in rows:
        last_seen = datetime.fromisoformat(r["last_seen"])
        seconds_ago = (now_ist() - last_seen).total_seconds()
        live_status = r["status"] if seconds_ago < 90 else "offline"
        results.append({
            "employee_username": r["employee_username"],
            "activity_score": r["activity_score"],
            "status": live_status,
            "last_seen": r["last_seen"]
        })
    return jsonify(results)


# ---------------- RECORDINGS LIBRARY (boss only, filterable) ----------------
@app.route("/api/recordings")
def recordings():
    if session.get("role") != "boss":
        return jsonify({"error": "Not authorized"}), 403
    employee_filter = request.args.get("employee", "").strip()
    conn = get_db()
    if employee_filter:
        rows = conn.execute("""
            SELECT id, employee_username, filepath, activity_score, status, created_at
            FROM recordings WHERE account_id=? AND filepath IS NOT NULL AND employee_username=?
            ORDER BY created_at DESC LIMIT 200
        """, (session["account_id"], employee_filter)).fetchall()
    else:
        rows = conn.execute("""
            SELECT id, employee_username, filepath, activity_score, status, created_at
            FROM recordings WHERE account_id=? AND filepath IS NOT NULL
            ORDER BY created_at DESC LIMIT 200
        """, (session["account_id"],)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/recordings/<int:rec_id>", methods=["DELETE"])
def delete_recording(rec_id):
    if session.get("role") != "boss":
        return jsonify({"error": "Not authorized"}), 403
    conn = get_db()
    row = conn.execute("SELECT * FROM recordings WHERE id=? AND account_id=?",
                        (rec_id, session["account_id"])).fetchone()
    if row and row["filepath"]:
        path = os.path.join(SCREENSHOT_DIR, str(session["account_id"]), row["filepath"])
        if os.path.exists(path):
            os.remove(path)
    conn.execute("DELETE FROM recordings WHERE id=?", (rec_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/recordings", methods=["DELETE"])
def delete_all_recordings():
    if session.get("role") != "boss":
        return jsonify({"error": "Not authorized"}), 403
    account_id = session["account_id"]
    employee_filter = request.args.get("employee", "").strip()
    conn = get_db()

    if employee_filter:
        rows = conn.execute(
            "SELECT * FROM recordings WHERE account_id=? AND employee_username=?",
            (account_id, employee_filter)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM recordings WHERE account_id=?", (account_id,)).fetchall()

    deleted_count = 0
    for row in rows:
        if row["filepath"]:
            path = os.path.join(SCREENSHOT_DIR, str(account_id), row["filepath"])
            if os.path.exists(path):
                os.remove(path)
        deleted_count += 1

    if employee_filter:
        conn.execute("DELETE FROM recordings WHERE account_id=? AND employee_username=?", (account_id, employee_filter))
    else:
        conn.execute("DELETE FROM recordings WHERE account_id=?", (account_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "deleted": deleted_count})


@app.route("/screenshots/<filename>")
def serve_screenshot(filename):
    if session.get("role") != "boss":
        return "", 401
    return send_from_directory(os.path.join(SCREENSHOT_DIR, str(session["account_id"])), filename)


# ---------------- ADMIN ----------------
@app.route("/api/admin/accounts")
def admin_accounts():
    if session.get("role") != "admin":
        return jsonify({"error": "Not authorized"}), 403
    conn = get_db()
    rows = conn.execute("SELECT * FROM accounts ORDER BY created_at DESC").fetchall()
    results = []
    for r in rows:
        emp_count = conn.execute("SELECT COUNT(*) as c FROM employees WHERE account_id=?", (r["id"],)).fetchone()["c"]
        results.append({
            "id": r["id"], "name": r["name"], "company": r["company"], "email": r["email"],
            "employee_limit": r["employee_limit"], "employees_used": emp_count,
            "validity_date": r["validity_date"], "is_valid": is_account_valid(r),
            "created_at": r["created_at"]
        })
    conn.close()
    return jsonify(results)


@app.route("/api/admin/accounts/<int:account_id>/validity", methods=["POST"])
def admin_update_validity(account_id):
    if session.get("role") != "admin":
        return jsonify({"error": "Not authorized"}), 403
    data = request.json
    conn = get_db()
    conn.execute("UPDATE accounts SET validity_date=? WHERE id=?", (data.get("validity_date"), account_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/requests")
def admin_requests():
    if session.get("role") != "admin":
        return jsonify({"error": "Not authorized"}), 403
    conn = get_db()
    rows = conn.execute("""
        SELECT r.id, r.account_id, r.requested_limit, r.status, r.created_at,
               a.company, a.email, a.employee_limit as current_limit
        FROM employee_requests r JOIN accounts a ON r.account_id = a.id
        WHERE r.status='pending'
        ORDER BY r.created_at ASC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/admin/requests/<int:req_id>/<action>", methods=["POST"])
def admin_resolve_request(req_id, action):
    if session.get("role") != "admin":
        return jsonify({"error": "Not authorized"}), 403
    if action not in ("approve", "deny"):
        return jsonify({"error": "Invalid action"}), 400
    conn = get_db()
    req = conn.execute("SELECT * FROM employee_requests WHERE id=?", (req_id,)).fetchone()
    if not req:
        conn.close()
        return jsonify({"error": "Request not found"}), 404
    if action == "approve":
        conn.execute("UPDATE accounts SET employee_limit=? WHERE id=?", (req["requested_limit"], req["account_id"]))
        conn.execute("UPDATE employee_requests SET status='approved' WHERE id=?", (req_id,))
    else:
        conn.execute("UPDATE employee_requests SET status='denied' WHERE id=?", (req_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ---------------- FRONTEND ----------------
@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


# ---------------- BACKGROUND: AUTO-DELETE OLD RECORDINGS ----------------
def cleanup_loop():
    while True:
        try:
            conn = get_db()
            settings_rows = conn.execute("SELECT * FROM settings").fetchall()
            for s in settings_rows:
                cutoff = now_ist() - timedelta(days=s["retention_days"])
                old_rows = conn.execute(
                    "SELECT * FROM recordings WHERE account_id=? AND created_at < ?",
                    (s["account_id"], cutoff.isoformat())
                ).fetchall()
                for row in old_rows:
                    if row["filepath"]:
                        path = os.path.join(SCREENSHOT_DIR, str(s["account_id"]), row["filepath"])
                        if os.path.exists(path):
                            os.remove(path)
                    conn.execute("DELETE FROM recordings WHERE id=?", (row["id"],))
            conn.commit()
            conn.close()
        except Exception as e:
            print("Cleanup error:", e)
        time.sleep(300)


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


# Runs regardless of how the app is started (gunicorn on a host OR direct python locally)
init_db()
threading.Thread(target=cleanup_loop, daemon=True).start()


if __name__ == "__main__":
    local_ip = get_local_ip()
    print("=" * 60)
    print("TeamPulse server starting")
    print(f"On this computer:  http://localhost:5000")
    print(f"From another device on the same WiFi:  http://{local_ip}:5000")
    print(f"Admin dashboard: log in with username 'admin' and password 'admin'")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=False)
