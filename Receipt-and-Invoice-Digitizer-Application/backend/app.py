from flask import Flask, request, jsonify, render_template, redirect, url_for, session, send_from_directory
from werkzeug.utils import secure_filename
import sqlite3
import bcrypt
import os
from datetime import datetime
import secrets
import jwt
import ollama
import json
#for sending mail
from flask_mail import Mail, Message
import uuid
from flask import flash
def detect_intent_llm(message):

    intent_list = [i["tag"] for i in intents["intents"]]

    prompt = f"""
You are an intent classifier for a receipt management system.

Available intents:
{intent_list}

User message:
"{message}"

Return ONLY the intent tag.
If none match, return: none
"""

    response = ollama.chat(
        model="mistral",
        messages=[
            {"role": "user", "content": prompt}
        ],
        options={
            "num_predict": 5,
            "temperature": 0
        }
    )

    intent = response["message"]["content"].strip().lower()

    return intent


# OCR IMPORT
from ocr import perform_ocr, extract_invoice_details

# Load intents
with open("chat_intents.json", "r", encoding="utf-8-sig") as f:
    intents = json.load(f)

# INTENT DETECTION FUNCTION
def detect_intent(message):

    message = message.lower()

    for intent in intents["intents"]:
        for pattern in intent["patterns"]:
            if pattern.lower() in message:
                return intent["tag"]

    return None


# ---------- FLASK APP SETUP ----------
# BASE_DIR = backend/ folder (where app.py lives)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# frontend/ folder is one level up from backend/
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")

app = Flask(
    __name__,
    template_folder=os.path.join(FRONTEND_DIR, "templates"),   # frontend/templates/
    static_folder=FRONTEND_DIR,                                  # frontend/ (serves back_drop, i18n, etc.)
    static_url_path="/static"                                    # accessed as /static/back_drop/...
)

app.secret_key = secrets.token_hex(16)
# ---------------- EMAIL CONFIG ----------------
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'noreply.invoicedigitizer@gmail.com'
app.config['MAIL_PASSWORD'] = 'okztpqikspemnrlf'

mail = Mail(app)
# store reset tokens
reset_tokens = {}

# safer upload path
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), "uploads")
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------- LOAD MISTRAL INTO RAM ----------
def load_mistral_model():

    try:

        print("Loading Mistral model into RAM...")

        ollama.chat(
            model="mistral",
            messages=[
                {"role": "user", "content": "hello"}
            ],
            options={
                "num_predict": 1,
                "keep_alive": "30m"
            }
        )

        print("Mistral loaded successfully.")

    except Exception as e:

        print("Failed to load model:", e)


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
    # If already logged in, redirect to appropriate dashboard
    if 'user_id' in session:
        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("dashboard"))

    # Otherwise show the landing page
    return render_template("landing.html")


# ---------- SEND RESET EMAIL ----------
@app.route('/send-reset-mail', methods=['POST'])
def send_reset_mail():

    email = request.form.get('email')

    if not email:
        return jsonify({"success": False, "message": "Email required"})

    # check if email exists
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("SELECT email FROM users WHERE email=?", (email,))
    user = cursor.fetchone()

    conn.close()

    if not user:
        return jsonify({"success": False, "message": "Email not registered"})

    # generate token
    token = str(uuid.uuid4())

    reset_tokens[token] = {
        "email": email,
        "time": datetime.now()
    }

    reset_link = f"http://127.0.0.1:5000/reset-password/{token}"

    try:
        msg = Message(
            subject="Password Reset - Invoice Digitizer",
            sender=app.config['MAIL_USERNAME'],
            recipients=[email]
        )

        msg.body = f"""
Hello,

Click the link below to reset your password:

{reset_link}

This link will expire soon.

If you didn't request this, please ignore this email.
"""

        mail.send(msg)

        return jsonify({
            "success": True,
            "message": "Reset email sent"
        })

    except Exception as e:
        print("MAIL ERROR:", e)

        return jsonify({
            "success": False,
            "message": "Failed to send email"
        })

# ---------- RESET PASSWORD PAGE ----------
@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):

    if token not in reset_tokens:
        return "Invalid or expired token"

    token_data = reset_tokens[token]

    # expire token after 15 minutes
    if (datetime.now() - token_data["time"]).seconds > 900:
        reset_tokens.pop(token)
        return "Reset link expired"

    if request.method == 'POST':

        password = request.form.get('new_password')
        confirm = request.form.get('confirm_password')

        if password != confirm:
            flash("Passwords do not match")
            return redirect(request.url)

        email = token_data["email"]

        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()

        cursor.execute(
            "UPDATE users SET password=? WHERE email=?",
            (hashed, email)
        )

        conn.commit()
        conn.close()

        reset_tokens.pop(token)

        flash("Password reset successful. Please login.")
        return redirect(url_for('index'))

    return render_template('reset_password.html')

# ---------- LOGIN PAGE ----------
@app.route("/login")
def login_page():
    if 'user_id' in session:
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


# ---------- BILL DIGITIZER ----------
@app.route("/bill-digitizer")
def bill_digitizer():

    if 'user_id' not in session:
        return redirect(url_for('index'))

    return render_template("bill_digitizer.html")


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


# ---------- CHATBOT ----------
@app.route("/api/chat", methods=["POST"])
def chatbot():

    if 'user_id' not in session:
        return jsonify({"reply": "Please login first."})

    data = request.json
    user_message = data.get("message", "")

    intent = detect_intent_llm(user_message)

    # ---------- VALIDATE INTENT ----------
    valid_intents = [i["tag"] for i in intents["intents"]]

    if intent not in valid_intents:
        intent = None

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    user_id = session["user_id"]

    try:

        # ---------- GREETING ----------
        if intent == "greeting":
            reply = "Hi! How can I help?"

        # ---------- TOTAL SPENDING ----------
        elif intent == "total_spending":

            cursor.execute(
                "SELECT SUM(total_amount) FROM receipts WHERE user_id=?",
                (user_id,)
            )

            total = cursor.fetchone()[0] or 0
            reply = f"You have spent ₹{total:.2f} in total."

        # ---------- RECEIPT COUNT ----------
        elif intent == "receipt_count":

            cursor.execute(
                "SELECT COUNT(*) FROM receipts WHERE user_id=?",
                (user_id,)
            )

            count = cursor.fetchone()[0]
            reply = f"You have {count} receipts stored."

        # ---------- TOTAL TAX ----------
        elif intent == "total_tax":

            cursor.execute(
                "SELECT SUM(tax) FROM receipts WHERE user_id=?",
                (user_id,)
            )

            tax = cursor.fetchone()[0] or 0
            reply = f"Your total tax paid is ₹{tax:.2f}."

        # ---------- TOP VENDOR ----------
        elif intent == "top_vendor":

            cursor.execute("""
                SELECT vendor_name, SUM(total_amount)
                FROM receipts
                WHERE user_id=?
                GROUP BY vendor_name
                ORDER BY SUM(total_amount) DESC
                LIMIT 1
            """, (user_id,))

            row = cursor.fetchone()

            if row:
                vendor, amount = row
                reply = f"You spent the most at {vendor} (₹{amount:.2f})."
            else:
                reply = "No receipts found."

        # ---------- MONTHLY SPENDING ----------
        elif intent == "monthly_spending":

            cursor.execute("""
                SELECT SUM(total_amount)
                FROM receipts
                WHERE user_id=?
                AND strftime('%Y-%m', date) = strftime('%Y-%m','now')
            """, (user_id,))

            total = cursor.fetchone()[0] or 0
            reply = f"You spent ₹{total:.2f} this month."

        # ---------- DEFAULT → MISTRAL ----------
        else:

            response = ollama.chat(
                model="mistral",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an AI assistant inside a receipt management system. Answer briefly and help users understand receipts, invoices, taxes and expenses."
                    },
                    {
                        "role": "user",
                        "content": user_message
                    }
                ],
                options={
                    "num_predict": 40,
                    "temperature": 0.2,
                    "keep_alive": "30m"
                }
            )

            reply = response["message"]["content"]

        conn.close()

        return jsonify({"reply": reply})

    except Exception as e:

        conn.close()

        print("Chatbot error:", e)

        return jsonify({"reply": "AI server error."})


# ---------- SERVE UPLOADED FILES ----------
@app.route("/uploads/<filename>")
def uploaded_file(filename):

    if 'user_id' not in session:
        return "Not authenticated", 401

    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == "__main__":
    load_mistral_model()
    app.run(debug=True, port=5000)
