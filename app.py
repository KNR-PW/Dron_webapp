import os
import sys
import time
import logging
import base64
from io import BytesIO
from datetime import datetime, UTC
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_from_directory,
    abort,
    Response,
    redirect,
    url_for
)

from flask_login import (LoginManager, UserMixin, login_user, login_required, logout_user, current_user)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from urllib.parse import urlparse, urljoin
from PIL import Image
from werkzeug.middleware.proxy_fix import ProxyFix

###############################################################################
# Flask initialisation & configuration                                        #
###############################################################################

app = Flask(__name__)

# Respect reverse proxy headers (X-Forwarded-*) when behind a load balancer
if os.getenv("TRUST_PROXY", "1").lower() in ("1", "true", "yes"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# ---- Core settings ----------------------------------------------------------
# Generate or load a persistent secret key (unless provided via env)
def _get_secret_key() -> bytes:
    env_key = os.getenv("SECRET_KEY")
    if env_key:
        # allow hex/base64/plain strings; bytes also accepted by Flask
        try:
            return env_key.encode("utf-8")
        except Exception:
            return env_key  # type: ignore
    secret_path = os.path.join("data", "secret.key")
    os.makedirs(os.path.dirname(secret_path), exist_ok=True)
    if os.path.exists(secret_path):
        try:
            with open(secret_path, "rb") as f:
                return f.read()
        except Exception:
            pass
    import secrets
    key = secrets.token_bytes(32)
    try:
        with open(secret_path, "wb") as f:
            f.write(key)
    except Exception:
        # fallback to in-memory key only
        print("Warning: Failed to persist secret key; sessions may reset on restart.")
    return key

secret_key = _get_secret_key()

# Determine environment (prod vs dev) and preferred URL scheme
_is_prod = os.getenv("FLASK_DEBUG", "false").lower() != "true"
_preferred_scheme = os.getenv("PREFERRED_URL_SCHEME", "https" if _is_prod else "http")

app.config.update(
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,  # 16 MB upload limit
    UPLOAD_FOLDER=os.getenv("UPLOAD_FOLDER", "data/images"),
    LOG_FILE=os.getenv("LOG_FILE", "data/mission.log"),
    SECRET_KEY=secret_key,
    SESSION_COOKIE_SAMESITE="Lax",
    REMEMBER_COOKIE_SAMESITE="Lax",
    # In dev on localhost we don't require HTTPS; in prod enforce Secure cookies
    SESSION_COOKIE_SECURE=False,
    REMEMBER_COOKIE_SECURE=False,
    PREFERRED_URL_SCHEME=_preferred_scheme,
)

if _is_prod:
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        REMEMBER_COOKIE_SECURE=True,
    )

#----- Flask-Login setup -------------------------------------------------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."

#----- User management -------------------------------------------------------
class User(UserMixin):
    def __init__(self, id , username,  password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

# In-memory user store (for demo purposes)
default_admin_passworld = os.getenv("ADMIN_PASSWORD", "admin")

users = {
    "admin": User(id=1, username="admin", password_hash=generate_password_hash(default_admin_passworld))
}

@login_manager.user_loader
def load_user(user_id):
    # Flask-Login stores user_id as a string in the session; ensure string comparison
    for user in users.values():
        if str(user.id) == str(user_id):
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
    "last_update": datetime.now(UTC).isoformat(),
}

latest_image: dict | None = None
mission_log: list[dict] = []

###############################################################################
# Helper utilities                                                            #
###############################################################################

def log_message(level: str, message: str) -> None:
    """Append message to in‑memory and file logs (rolling buffer)."""
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": level,
        "message": message,
    }
    mission_log.append(entry)
    logging.log(getattr(logging, level.upper(), logging.INFO), message)

    # keep at most 1000 entries in memory
    if len(mission_log) > 1000:
        mission_log.pop(0)

def ensure_upload_dirs():
    """Ensure all required directories exist and are writable"""
    paths = [
        app.config["UPLOAD_FOLDER"],
        os.path.dirname(app.config["LOG_FILE"])
    ]
    for path in paths:
        try:
            os.makedirs(path, exist_ok=True)
            # Test if directory is writable
            test_file = os.path.join(path, ".write_test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
        except Exception as e:
            app.logger.error(f"Failed to create/verify directory {path}: {e}")
            raise RuntimeError(f"Cannot access required directory: {path}")

###############################################################################
# Routes — Dashboard & API                                                    #
###############################################################################
# ---------------------------------------------------------------------------
# Authentication routes
# ---------------------------------------------------------------------------
def is_safe_url(target):
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        remember = request.form.get("remember") == "on"

        user = users.get(username)
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=remember)
            next_page = request.args.get("next") or request.form.get("next")
            if next_page and is_safe_url(next_page):
                return redirect(next_page)
            return redirect(url_for("dashboard"))
        else:
            return render_template("login.html", error="Invalid username or password")

    # GET
    next_page = request.args.get("next", "")
    return render_template("login.html", next=next_page)

@app.route("/logout")
@login_required
def logout():
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
            drone_status["last_update"] = datetime.now(UTC).isoformat()
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
        "timestamp": datetime.now(UTC).isoformat(),
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
        drone_status["last_update"] = datetime.now(UTC).isoformat()

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
                "timestamp": datetime.now(UTC).isoformat(),
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

# ---------------------------------------------------------------------------
# Health check                                                              #
# ---------------------------------------------------------------------------

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})

###############################################################################
# App entry‑point                                                             #
###############################################################################
try:
    import cv2  # type: ignore
    _CV2_AVAILABLE = True
except Exception:
    cv2 = None
    _CV2_AVAILABLE = False

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
        log_message("error", "OpenCV nie jest dostępne w środowisku")
        return jsonify({"success": False, "error": "OpenCV nie jest dostępne na serwerze"}), 503
    try:
        return Response(generate_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")
    except Exception as exc:
        log_message("error", f"Błąd strumienia wideo: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 503

if __name__ == "__main__":
    # Konfiguracja z env (Render ustawia PORT)
    app.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER", app.config.get("UPLOAD_FOLDER", "data/images"))
    app.config["LOG_FILE"] = os.getenv("LOG_FILE", app.config.get("LOG_FILE", "data/mission.log"))
    # Don't override SECRET_KEY unless explicitly provided
    if os.getenv("SECRET_KEY"):
        app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

    try:
        ensure_upload_dirs()
    except Exception as e:
        app.logger.error(f"Startup failed: {e}")
        sys.exit(1)

    log_message("info", "Drone web application started")

    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    app.run(host="0.0.0.0", port=port, threaded=True, debug=debug)
