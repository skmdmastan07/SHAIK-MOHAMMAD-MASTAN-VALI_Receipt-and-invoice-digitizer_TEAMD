from flask import Flask, request, jsonify, render_template, redirect, url_for, session, send_from_directory
from werkzeug.utils import secure_filename
import sqlite3
import bcrypt
import os
from datetime import datetime
import secrets
import jwt

# OCR IMPORT
from ocr import perform_ocr, extract_invoice_details

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# safer upload path
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), "uploads")
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------- DATABASE ----------
def init_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password BLOB NOT NULL,
            phone TEXT,
            role TEXT DEFAULT 'user'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS receipts(
            receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            vendor_name TEXT,
            invoice_number TEXT,
            date TEXT,
            total_amount REAL,
            tax REAL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # create default admin
    cursor.execute("SELECT * FROM users WHERE username='admin'")
    admin = cursor.fetchone()

    if not admin:
        password = bcrypt.hashpw("admin123".encode(), bcrypt.gensalt())

        cursor.execute("""
            INSERT INTO users(username,email,password,role)
            VALUES (?,?,?,?)
        """, ("admin", "admin@admin.com", password, "admin"))

        print("Admin created → username: admin  password: admin123")

    conn.commit()
    conn.close()


init_db()


# create uploads folder if not exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])


# ---------- HOME ----------
@app.route("/")
def index():

    if 'user_id' in session:

        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard"))

        return redirect(url_for("dashboard"))

    return render_template("login_page.html")


# ---------- ADMIN DASHBOARD ----------
@app.route("/admin")
def admin_dashboard():

    if session.get("role") != "admin":
        return redirect("/")

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    # total users
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    # total uploads
    cursor.execute("SELECT COUNT(*) FROM receipts")
    total_uploads = cursor.fetchone()[0]

    # uploads today
    cursor.execute("""
        SELECT COUNT(*) FROM receipts
        WHERE DATE(upload_date) = DATE('now')
    """)
    uploads_today = cursor.fetchone()[0]

    # uploads this week
    cursor.execute("""
        SELECT COUNT(*) FROM receipts
        WHERE upload_date >= DATE('now','-7 day')
    """)
    uploads_week = cursor.fetchone()[0]

    # recent uploads
    cursor.execute("""
        SELECT users.username,
               receipts.vendor_name,
               receipts.invoice_number,
               receipts.total_amount,
               receipts.upload_date
        FROM receipts
        JOIN users ON receipts.user_id = users.id
        ORDER BY receipts.upload_date DESC
        LIMIT 10
    """)

    recent_uploads = cursor.fetchall()

    # users overview
    cursor.execute("""
        SELECT users.id, users.username, users.email,
        COUNT(receipts.receipt_id)
        FROM users
        LEFT JOIN receipts
        ON users.id = receipts.user_id
        GROUP BY users.id
    """)

    users_overview = cursor.fetchall()

    conn.close()

    total_processed = total_uploads

    return render_template(
        "admin_dashboard.html",
        total_users=total_users,
        total_uploads=total_uploads,
        total_processed=total_processed,
        uploads_today=uploads_today,
        uploads_week=uploads_week,
        recent_uploads=recent_uploads,
        users_overview=users_overview
    )
    
# ---------- ADMIN VIEW USER BILLS ----------
@app.route("/admin/user/<int:user_id>")
def admin_view_user(user_id):

    if session.get("role") != "admin":
        return redirect("/")

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    # get user info
    cursor.execute("SELECT username, email FROM users WHERE id=?", (user_id,))
    user = cursor.fetchone()

    # get receipts uploaded by this user
    cursor.execute("""
        SELECT vendor_name, invoice_number, total_amount, upload_date, filename
        FROM receipts
        WHERE user_id=?
        ORDER BY upload_date DESC
    """, (user_id,))

    user_receipts = cursor.fetchall()

    conn.close()

    return render_template(
        "admin_user_receipts.html",
        user=user,
        user_receipts=user_receipts
    )
    
    
# ---------- GOOGLE LOGIN ----------
@app.route("/api/google-login", methods=["POST"])
def google_login():

    token = request.json.get("token")

    user = jwt.decode(token, options={"verify_signature": False})

    session["user_id"] = user["email"]
    session["username"] = user["name"]
    session["role"] = "user"

    return jsonify({"success": True})


# ---------- REGISTER PAGE ----------
@app.route("/register_page")
def register_page():
    return render_template("register_page.html")


# ---------- FORGOT PASSWORD ----------
@app.route("/forgot_password_page")
def forgot_password_page():
    return render_template("forgotpassword.html")


# ---------- USER DASHBOARD ----------
@app.route("/dashboard")
def dashboard():

    if 'user_id' not in session:
        return redirect(url_for('index'))

    return render_template("home.html")


# ---------- REGISTER ----------
@app.route("/api/register", methods=["POST"])
def register():

    username = request.form["username"]
    email = request.form["email"]
    password = request.form["password"]
    phone = request.form.get("phone", "")

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE username=? OR email=?", (username, email))

    if cursor.fetchone():
        conn.close()
        return jsonify({"success": False, "message": "User already exists"}), 400

    cursor.execute("""
        INSERT INTO users(username,email,password,phone)
        VALUES (?,?,?,?)
    """, (username, email, hashed, phone))

    conn.commit()
    conn.close()

    return jsonify({"success": True})


# ---------- LOGIN ----------
@app.route("/api/login", methods=["POST"])
def login():

    user_input = request.form["username"]
    password = request.form["password"]

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id,username,password,role
        FROM users
        WHERE username=? OR email=?
    """, (user_input, user_input))

    result = cursor.fetchone()
    conn.close()

    if not result:
        return jsonify({"success": False}), 404

    user_id, username, stored_password, role = result

    if bcrypt.checkpw(password.encode(), stored_password):

        session['user_id'] = user_id
        session['username'] = username
        session['role'] = role

        return jsonify({"success": True})

    return jsonify({"success": False}), 401


# ---------- LOGOUT ----------
@app.route("/api/logout", methods=["POST"])
def logout():

    session.clear()

    return jsonify({"success": True})


# ---------- UPLOAD RECEIPT ----------
@app.route("/api/upload", methods=["POST"])
def upload_receipt():

    if 'user_id' not in session:
        return jsonify({"success": False}), 401

    if 'file' not in request.files:
        return jsonify({"success": False}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({"success": False}), 400

    if file and allowed_file(file.filename):

        filename = secure_filename(file.filename)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{filename}"

        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        print("File saved:", filepath)

        # OCR SAFE BLOCK
        try:
            text = perform_ocr(filepath)
            details = extract_invoice_details(text)
        except Exception as e:
            print("OCR ERROR:", e)
            details = {}

        vendor = details.get("Vendor")
        invoice_number = details.get("Invoice Number")
        invoice_date = details.get("Date")

        try:
            total_amount = float(details.get("Total Amount") or 0)
        except:
            total_amount = 0

        try:
            tax = float(details.get("Tax") or 0)
        except:
            tax = 0

        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO receipts(user_id,filename,vendor_name,invoice_number,date,total_amount,tax)
            VALUES (?,?,?,?,?,?,?)
        """, (
            session['user_id'],
            filename,
            vendor,
            invoice_number,
            invoice_date,
            total_amount,
            tax
        ))

        receipt_id = cursor.lastrowid

        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "receipt_id": receipt_id,
            "data": details
        })

    return jsonify({"success": False})


# ---------- GET RECEIPTS ----------
@app.route("/api/receipts")
def get_receipts():

    if 'user_id' not in session:
        return jsonify({"success": False}), 401

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT receipt_id,filename,upload_date,vendor_name,invoice_number,date,total_amount,tax
        FROM receipts
        WHERE user_id=?
        ORDER BY upload_date DESC
    """, (session['user_id'],))

    receipts = []

    for row in cursor.fetchall():
        receipts.append({
            "receipt_id": row[0],
            "filename": row[1],
            "upload_date": row[2],
            "vendor_name": row[3],
            "invoice_number": row[4],
            "date": row[5],
            "total_amount": row[6],
            "tax": row[7]
        })

    conn.close()

    return jsonify({"success": True, "receipts": receipts})


# ---------- DELETE RECEIPT ----------
@app.route("/api/receipts/<int:receipt_id>", methods=["DELETE"])
def delete_receipt(receipt_id):

    if 'user_id' not in session:
        return jsonify({"success": False}), 401

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute(
        "SELECT filename FROM receipts WHERE receipt_id=? AND user_id=?",
        (receipt_id, session['user_id'])
    )

    result = cursor.fetchone()

    if result:

        filename = result[0]
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        cursor.execute(
            "DELETE FROM receipts WHERE receipt_id=? AND user_id=?",
            (receipt_id, session['user_id'])
        )

        conn.commit()

        if os.path.exists(filepath):
            os.remove(filepath)

        conn.close()

        return jsonify({"success": True})

    conn.close()

    return jsonify({"success": False}), 404


# ---------- ANALYTICS ----------
@app.route("/api/analytics/spending")
def analytics_spending():

    if 'user_id' not in session:
        return jsonify({"success": False}), 401

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT date,
               SUM(total_amount),
               SUM(tax),
               COUNT(*)
        FROM receipts
        WHERE user_id=?
        GROUP BY date
        ORDER BY date
    """, (session['user_id'],))

    rows = cursor.fetchall()

    data = []
    grand_total = 0
    grand_tax = 0
    total_receipts = 0

    for row in rows:

        date, daily_total, daily_tax, count = row

        daily_total = daily_total or 0
        daily_tax = daily_tax or 0

        grand_total += daily_total
        grand_tax += daily_tax
        total_receipts += count

        data.append({
            "date": date,
            "daily_total": daily_total,
            "daily_tax": daily_tax,
            "receipt_count": count
        })

    avg_amount = grand_total / total_receipts if total_receipts else 0

    conn.close()

    return jsonify({
        "success": True,
        "data": data,
        "summary": {
            "grand_total": grand_total,
            "grand_tax": grand_tax,
            "total_receipts": total_receipts,
            "avg_amount": avg_amount
        }
    })


# ---------- SERVE FILE ----------
@app.route("/uploads/<filename>")
def uploaded_file(filename):

    if 'user_id' not in session:
        return "Not authenticated", 401

    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == "__main__":
    app.run(debug=True, port=5000)