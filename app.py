import os
import time
import logging
import base64
from io import BytesIO
from datetime import datetime
from itertools import cycle
import pathlib
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_from_directory,
    abort,
    redirect,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image

###############################################################################
# Flask initialisation & configuration                                        #
###############################################################################

app = Flask(__name__)

# ---- Core settings ----------------------------------------------------------
# Generate a secure SECRET_KEY if not provided via environment variable
secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    import secrets
    secret_key = secrets.token_hex(32)
    print("WARNING: Using generated SECRET_KEY. Set SECRET_KEY environment variable for production!")

app.config.update(
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,  # 16 MB upload limit
    UPLOAD_FOLDER="data/images",
    LOG_FILE="data/mission.log",
    SECRET_KEY=secret_key,
)

# ---- Flask-Login setup -----------------------------------------------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."

# ---- User Management -------------------------------------------------------
class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

# Simple in-memory user database (in production, use a real database)
# Default credentials can be set via environment variables
default_admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
if default_admin_password == "admin123":
    print("WARNING: Using default admin password. Set ADMIN_PASSWORD environment variable for production!")

users = {
    "admin": User(
        id="1",
        username="admin",
        password_hash=generate_password_hash(default_admin_password),
    )
}

@login_manager.user_loader
def load_user(user_id):
    for user in users.values():
        if user.id == user_id:
            return user
    return None

# ---- Ensure runtime directories exist --------------------------------------
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(os.path.dirname(app.config["LOG_FILE"]), exist_ok=True)

# ---- Logging ---------------------------------------------------------------
logging.basicConfig(
    filename=app.config["LOG_FILE"],
    level=logging.INFO,
    format="%(asctime)s — %(levelname)s — %(message)s",
)

###############################################################################
# In‑memory data stores                                                       #
###############################################################################

drone_status = {
    "altitude": 0.0,
    "speed": 0.0,
    "battery_percent": 100,
    "battery_voltage": 0,
    "gps_global": "0.0,0.0",
    "gps_relative": "0.0,0.0",
    "mission_time": "00:00:00",
    "flight_mode": "INIT",
    "last_update": datetime.utcnow().isoformat(),
}

latest_image: dict | None = None
mission_log: list[dict] = []

###############################################################################
# Helper utilities                                                            #
###############################################################################

def log_message(level: str, message: str) -> None:
    """Append message to in‑memory and file logs (rolling buffer)."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "level": level,
        "message": message,
    }
    mission_log.append(entry)
    logging.log(getattr(logging, level.upper(), logging.INFO), message)

    # keep at most 1000 entries in memory
    if len(mission_log) > 1000:
        mission_log.pop(0)


###############################################################################
# Routes — Dashboard & API                                                    #
###############################################################################

# ---------------------------------------------------------------------------
# Authentication routes
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    """Handle user login"""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        remember = request.form.get("remember") == "on"
        
        user = users.get(username)
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=remember)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("dashboard"))
        else:
            return render_template("login.html", error="Invalid username or password")
    
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    """Handle user logout"""
    logout_user()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    """Main dashboard page"""
    return render_template(
        "index.html",
        status=drone_status,
        latest_image=latest_image,
        logs=mission_log[-100:],  # last 100 log entries
    )

# ---------------------------------------------------------------------------
# Status API
# ---------------------------------------------------------------------------

@app.route("/api/status", methods=["GET", "POST"])
@login_required
def handle_status():
    global drone_status, latest_image

    if request.method == "POST":
        new_data = request.get_json(silent=True)
        if new_data:
            drone_status.update(new_data)
            drone_status["last_update"] = datetime.utcnow().isoformat()
            # log_message("info", f"Status updated: {new_data}")
        return jsonify({"success": True, "status": drone_status})

    # GET: current status + latest image
    return jsonify({
        **drone_status,
        "latest_image": latest_image,
    })

# ---------------------------------------------------------------------------
# Image uploads                                                               #
# ---------------------------------------------------------------------------

@app.route("/api/image", methods=["POST"])
@login_required
def upload_image():
    global latest_image

    if "image" not in request.files:
        return jsonify({"success": False, "error": "No image provided"}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"success": False, "error": "Empty filename"}), 400

    filename = secure_filename(f"{int(time.time())}_{file.filename}")
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)

    latest_image = {
        "filename": filename,
        "timestamp": datetime.utcnow().isoformat(),
        "size": os.path.getsize(filepath),
    }
    # log_message("info", f"New image received: {filename}")
    return jsonify({"success": True, "image": latest_image})

@app.route("/images/<path:filename>")
@login_required
def serve_image(filename):
    if ".." in filename or filename.startswith("/"):
        abort(400)
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# ---------------------------------------------------------------------------
# Mission log API                                                             #
# ---------------------------------------------------------------------------

@app.route("/api/log", methods=["GET", "POST", "DELETE"])
@login_required
def handle_log():
    global mission_log

    if request.method == "POST":
        data = request.get_json(silent=True)
        if data and "message" in data:
            level = data.get("level", "info")
            log_message(level, data["message"])
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Invalid log data"}), 400

    if request.method == "DELETE":
        mission_log = []
        return jsonify({"success": True})

    # GET
    return jsonify({"logs": mission_log[-100:]})

# ---------------------------------------------------------------------------
# Telemetry (composite) API                                                   #
# ---------------------------------------------------------------------------

@app.route("/api/telemetry", methods=["POST"])
@login_required
def telemetry_endpoint():
    global drone_status, latest_image

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    # 1) status fields -------------------------------------------------------
    if "status" in data:
        drone_status.update(data["status"])
        drone_status["last_update"] = datetime.utcnow().isoformat()

    # 2) optional image in base64 -------------------------------------------
    if "image" in data and data["image"]:
        try:
            img_data = data["image"].split(",", 1)[1]  # remove data:image/... prefix
            img = Image.open(BytesIO(base64.b64decode(img_data)))
            filename = f"{int(time.time())}_drone_capture.jpg"
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            img.save(filepath, "JPEG", quality=85)

            latest_image = {
                "filename": filename,
                "timestamp": datetime.utcnow().isoformat(),
                "size": os.path.getsize(filepath),
            }
        except Exception as exc:
            log_message("error", f"Failed to process image: {exc}")

    # 3) additional log messages -------------------------------------------
    if "logs" in data:
        for log_entry in data["logs"]:
            level = log_entry.get("level", "info")
            log_message(level, log_entry.get("message", ""))

    return jsonify({"success": True})

# ---------------------------------------------------------------------------
# Uploaded images list & clear                                                #
# ---------------------------------------------------------------------------

@app.route("/api/images", methods=["GET", "DELETE"])
@login_required
def images_api():
    folder = app.config["UPLOAD_FOLDER"]

    if request.method == "DELETE":
        errors: list[str] = []
        for filename in os.listdir(folder):
            try:
                os.remove(os.path.join(folder, filename))
            except Exception as exc:
                errors.append(f"{filename}: {exc}")
        if errors:
            log_message("error", f"Image delete errors: {errors}")
            return jsonify({"success": False, "error": errors}), 500
        log_message("info", "Gallery cleared")
        return jsonify({"success": True})

    # GET — list of files
    images = sorted(os.listdir(folder), reverse=True)
    return jsonify({"images": images})

###############################################################################
# App entry‑point                                                             #
###############################################################################
try:
    import cv2  # type: ignore
    _CV2_AVAILABLE = True
except Exception:
    cv2 = None
    _CV2_AVAILABLE = False

from flask import Response

def generate_frames():
    if not _CV2_AVAILABLE:
                raise RuntimeError("OpenCV is not available in the environment")
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
                raise RuntimeError("Camera access unavailable (Render does not provide camera access)")
    while True:
        success, frame = camera.read()
        if not success:
            break
        ret, buffer = cv2.imencode(".jpg", frame)
        if not ret:
            break
        frame_bytes = buffer.tobytes()
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n")

@app.route("/video_feed")
@login_required
def video_feed():
    if not _CV2_AVAILABLE:
                return jsonify({"success": False, "error": "OpenCV is not available on the server"}), 503
    try:
        return Response(generate_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")
    except Exception as exc:
                return jsonify({"success": False, "error": f"Stream unavailable: {exc}"}), 503





if __name__ == "__main__":
    # Konfiguracja z env (Render ustawia PORT)
    app.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER", app.config.get("UPLOAD_FOLDER", "data/images"))
    app.config["LOG_FILE"] = os.getenv("LOG_FILE", app.config.get("LOG_FILE", "data/mission.log"))
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", app.config.get("SECRET_KEY", "change-me"))

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(os.path.dirname(app.config["LOG_FILE"]), exist_ok=True)

    log_message("info", "Drone web application started")

    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    app.run(host="0.0.0.0", port=port, threaded=True, debug=debug)
