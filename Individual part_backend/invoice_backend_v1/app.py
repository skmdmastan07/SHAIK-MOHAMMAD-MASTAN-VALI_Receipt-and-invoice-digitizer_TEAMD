from flask import redirect
from flask import Flask, request, jsonify
import sqlite3
import bcrypt

app = Flask(__name__)

# ---------- DB INIT ----------
def init_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            email TEXT,
            password TEXT,
            phone TEXT
        )
    """)

    conn.commit()
    conn.close()

init_db()


# ---------- REGISTER API ----------
@app.route("/register", methods=["POST"])
def register():

    username = request.form["username"]
    email = request.form["email"]
    password = request.form["password"]
    phone = request.form["phone"]

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO users(username,email,password,phone)
        VALUES (?,?,?,?)
    """, (username, email, hashed, phone))

    conn.commit()
    conn.close()

    return "Registered Successfully"


# ---------- LOGIN API ----------
@app.route("/login", methods=["POST"])
def login():

    user_input = request.form["username"]
    password = request.form["password"]

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT password FROM users
        WHERE username=? OR email=?
    """, (user_input, user_input))

    result = cursor.fetchone()
    conn.close()

    if result is None:
        return "User not found"

    stored_password = result[0]

    if bcrypt.checkpw(password.encode(), stored_password):
        return "Login Successful"
    else:
        return "Invalid Password"
    
    
    
    
# ---------- FORGOT PASSWORD ----------
@app.route("/forgot-password", methods=["POST"])
def forgot_password():

    email = request.form["email"]

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    

    cursor.execute("SELECT * FROM users WHERE email=?", (email,))
    user = cursor.fetchone()

    conn.close()

    if user:
        return "Reset link sent (simulation)"
    else:
        return "Email not found"



# ---------- HOME ----------
@app.route("/")
def home():
    return "Backend Ready"


if __name__ == "__main__":
    app.run(debug=True)
