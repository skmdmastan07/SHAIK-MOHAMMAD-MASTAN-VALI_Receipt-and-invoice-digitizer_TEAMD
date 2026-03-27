from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------- Home Route ----------
@app.route("/")
def home():
    return "Flask API is running"

# ---------- GET API ----------
# Example: http://127.0.0.1:5000/hello?name=Mastan
@app.route("/hello", methods=["GET"])
def hello():
    name = request.args.get("name", "Guest")
    return jsonify({"message": f"Hello {name}"})

# ---------- POST API ----------
# Send JSON:
# { "num1": 5, "num2": 3 }
@app.route("/add", methods=["POST"])
def add():
    data = request.get_json()

    num1 = data["num1"]
    num2 = data["num2"]

    result = num1 + num2

    return jsonify({"result": result})

# ---------- Run Server ----------
if __name__ == "__main__":
    app.run(debug=True)
