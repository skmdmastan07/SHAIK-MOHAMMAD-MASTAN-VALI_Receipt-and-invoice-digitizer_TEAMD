from flask import Flask, request, jsonify, render_template, redirect, url_for, session, send_from_directory, jsonify
from werkzeug.utils import secure_filename
import sqlite3
import bcrypt
import os
from datetime import datetime
import secrets
import jwt

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ---------- DB INIT ----------
def init_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone TEXT
        )
    """)

    # Receipts table
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

    conn.commit()
    conn.close()

init_db()

# Create upload folder if it doesn't exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])


# ---------- HOME / LOGIN PAGE ----------
@app.route("/")
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login_page.html')


# ---------- Admin route ----------

@app.route("/admin")
def admin_dashboard():
    if 'role' not in session or session.get('role') != 'admin':
        return redirect("/")

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    # Total Users
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    conn.close()

    # Count uploads from uploads folder
    import os
    uploads_folder = "uploads"
    total_uploads = len(os.listdir(uploads_folder)) if os.path.exists(uploads_folder) else 0

    # Processed receipts (if you store them in DB)
    # If you have receipts table, replace this query
    total_processed = total_uploads

    return render_template(
        "admin_dashboard.html",
        total_users=total_users,
        total_uploads=total_uploads,
        total_processed=total_processed
    )


#----------------google api-------------------
@app.route("/api/google-login", methods=["POST"])
def google_login():
    token = request.json.get("token")

    # Decode token (DEV mode – no verification yet)
    user = jwt.decode(token, options={"verify_signature": False})

    # Use email as user_id (or DB id if you have one)
    session["user_id"] = user["email"]
    session["user_name"] = user["name"]

    return jsonify({"success": True})

# ---------- REGISTER PAGE ----------
@app.route("/register_page")
def register_page():
    return render_template('register_page.html')


# ---------- FORGOT PASSWORD PAGE ----------
@app.route("/forgot_password_page")
def forgot_password_page():
    return render_template('forgotpassword.html')


# ---------- DASHBOARD ----------
@app.route("/dashboard")
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    return render_template('home.html')


# ---------- REGISTER API ----------
@app.route("/api/register", methods=["POST"])
def register():
    try:
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]
        phone = request.form.get("phone", "")

        # Hash password
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()

        # Check if username or email already exists
        cursor.execute("SELECT * FROM users WHERE username=? OR email=?", (username, email))
        if cursor.fetchone():
            conn.close()
            return jsonify({"success": False, "message": "Username or email already exists"}), 400

        cursor.execute("""
            INSERT INTO users(username, email, password, phone)
            VALUES (?,?,?,?)
        """, (username, email, hashed, phone))

        conn.commit()
        conn.close()

        return jsonify({"success": True, "message": "Registration successful! Please login."})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ---------- LOGIN API ----------
@app.route("/api/login", methods=["POST"])
def login():
    try:
        user_input = request.form["username"]
        password = request.form["password"]

        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, username, password, role FROM users
            WHERE username=? OR email=?
        """, (user_input, user_input))

        result = cursor.fetchone()
        conn.close()

        if result is None:
            return jsonify({"success": False, "message": "User not found"}), 404

        user_id, username, stored_password, role = result

        if bcrypt.checkpw(password.encode(), stored_password):
            # Create session
            session['user_id'] = user_id
            session['username'] = username
            session['role'] = role
            return jsonify({"success": True, "message": "Login successful", "username": username})
        else:
            return jsonify({"success": False, "message": "Invalid password"}), 401

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ---------- LOGOUT ----------
@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True, "message": "Logged out successfully"})


# ---------- FORGOT PASSWORD ----------
@app.route("/api/forgot-password", methods=["POST"])
def forgot_password():
    try:
        email = request.form["email"]

        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM users WHERE email=?", (email,))
        user = cursor.fetchone()

        conn.close()

        if user:
            # In a real app, you would send an email here
            return jsonify({"success": True, "message": "Password reset link sent to your email (simulation)"})
        else:
            return jsonify({"success": False, "message": "Email not found"}), 404

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ---------- UPLOAD RECEIPT ----------
@app.route("/api/upload", methods=["POST"])
def upload_receipt():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Not authenticated"}), 401

    if 'file' not in request.files:
        return jsonify({"success": False, "message": "No file uploaded"}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({"success": False, "message": "No file selected"}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # Add timestamp to filename to make it unique
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # Save receipt info to database
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()

        # For now, we'll store basic info. In a real app, you'd use OCR here
        cursor.execute("""
            INSERT INTO receipts(user_id, filename, vendor_name, invoice_number, date, total_amount, tax)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session['user_id'], filename, "Sample Vendor", "INV-001", datetime.now().strftime("%Y-%m-%d"), 0.00, 0.00))

        receipt_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return jsonify({"success": True, "message": "Receipt uploaded successfully", "receipt_id": receipt_id})

    return jsonify({"success": False, "message": "Invalid file type"}), 400


# ---------- GET ALL RECEIPTS ----------
@app.route("/api/receipts", methods=["GET"])
def get_receipts():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Not authenticated"}), 401

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT receipt_id, filename, upload_date, vendor_name, invoice_number, date, total_amount, tax
        FROM receipts
        WHERE user_id = ?
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
        return jsonify({"success": False, "message": "Not authenticated"}), 401

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    # Get filename before deleting
    cursor.execute("SELECT filename FROM receipts WHERE receipt_id=? AND user_id=?", 
                   (receipt_id, session['user_id']))
    result = cursor.fetchone()

    if result:
        filename = result[0]
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Delete from database
        cursor.execute("DELETE FROM receipts WHERE receipt_id=? AND user_id=?", 
                      (receipt_id, session['user_id']))
        conn.commit()
        
        # Delete file
        if os.path.exists(filepath):
            os.remove(filepath)
        
        conn.close()
        return jsonify({"success": True, "message": "Receipt deleted"})
    
    conn.close()
    return jsonify({"success": False, "message": "Receipt not found"}), 404


# ---------- SERVE UPLOADED FILES ----------
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    if 'user_id' not in session:
        return "Not authenticated", 401
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash

if __name__ == "__main__":
    app.run(debug=True, port=5000)
    
    
    
    
# ---------- ADMIN DASHBOARD ----------   
@app.route("/admin-dashboard")
def admin_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index'))

    if session.get('role') != 'admin':
        return "Unauthorized Access", 403

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    # Total users
    cursor.execute("SELECT COUNT(*) FROM users WHERE role='user'")
    total_users = cursor.fetchone()[0]

    # Total receipts uploaded
    cursor.execute("SELECT COUNT(*) FROM receipts")
    total_uploads = cursor.fetchone()[0]

    conn.close()

    return render_template("admin_dashboard.html",
                           total_users=total_users,
                           total_uploads=total_uploads)