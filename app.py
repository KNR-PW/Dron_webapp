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
)
from werkzeug.utils import secure_filename
from PIL import Image

###############################################################################
# Flask initialisation & configuration                                        #
###############################################################################

app = Flask(__name__)

# ---- Core settings ----------------------------------------------------------
app.config.update(
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,  # 16 MB upload limit
    UPLOAD_FOLDER="data/images",
    LOG_FILE="data/mission.log",
    SECRET_KEY="your-secret-key-here",  # TODO: change in production
    GPS_POINTS_FILE="data/gps_points.txt",
)

# ---- Google Maps API key ----------------------------------------------------
def load_api_key():
    for name in ["kluczapi", "kluczapi.txt"]:
        path = pathlib.Path(name)
        if path.exists():
            key = path.read_text(encoding="utf-8").strip()
            if key:
                return key
    raise RuntimeError("📍 Plik 'kluczapi' lub 'kluczapi.txt' musi istnieć i zawierać poprawny klucz Google Maps!")

app.config["GOOGLE_MAPS_KEY"] = load_api_key()
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
    "battery": 100,
    "gps": "0.0,0.0",
    "signal_strength": -50,
    "mission_time": "00:00:00",
    "flight_mode": "INIT",
    "temperature": 25.0,
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

# ---- GPS point cycling ------------------------------------------------------

def _build_gps_cycle(path: str) -> cycle:
    """Return an itertools.cycle generator over lat,lon lines in *path*."""
    if not os.path.exists(path):
        logging.warning("GPS points file '%s' not found – creating an empty one", path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("52.2297,21.0122\n")  # Warsaw as default

    with open(path, "r", encoding="utf-8") as f:
        points = [ln.strip() for ln in f if ln.strip()]

    if not points:
        # Ensure at least one point to avoid StopIteration later on
        points = ["52.2297,21.0122"]

    return cycle(points)

_gps_cycle = _build_gps_cycle(app.config["GPS_POINTS_FILE"])

def get_next_gps() -> str:
    return next(_gps_cycle)

###############################################################################
# Routes — Dashboard & API                                                    #
###############################################################################

@app.route("/")
def dashboard():
    """Main dashboard page"""
    return render_template(
        "index.html",
        status=drone_status,
        latest_image=latest_image,
        logs=mission_log[-100:],  # last 100 log entries
        google_maps_key=app.config["GOOGLE_MAPS_KEY"],
    )

# ---------------------------------------------------------------------------
# Status API
# ---------------------------------------------------------------------------

@app.route("/api/status", methods=["GET", "POST"])
def handle_status():
    global drone_status, latest_image

    if request.method == "POST":
        new_data = request.get_json(silent=True)
        if new_data:
            drone_status.update(new_data)
            drone_status["last_update"] = datetime.utcnow().isoformat()
            log_message("info", f"Status updated: {new_data}")
        return jsonify({"success": True, "status": drone_status})

    # GET: current status + latest image
    return jsonify({
        **drone_status,
        "latest_image": latest_image,
    })

# ---------------------------------------------------------------------------
# Next‑GPS endpoint  (used by Google Maps JS)
# ---------------------------------------------------------------------------

@app.route("/api/next_gps")
def api_next_gps():
    """Return next GPS coordinate from the predefined list."""
    point = get_next_gps()  # e.g. "52.23,21.01"
    drone_status["gps"] = point
    drone_status["last_update"] = datetime.utcnow().isoformat()
    return jsonify({"gps": point})

# ---------------------------------------------------------------------------
# Image uploads                                                               #
# ---------------------------------------------------------------------------

@app.route("/api/image", methods=["POST"])
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
    log_message("info", f"New image received: {filename}")
    return jsonify({"success": True, "image": latest_image})

@app.route("/images/<path:filename>")
def serve_image(filename):
    if ".." in filename or filename.startswith("/"):
        abort(400)
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# ---------------------------------------------------------------------------
# Mission log API                                                             #
# ---------------------------------------------------------------------------

@app.route("/api/log", methods=["GET", "POST", "DELETE"])
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
import cv2
from flask import Response

def generate_frames():
    camera = cv2.VideoCapture(0)
    while True:
        success, frame = camera.read()
        if not success:
            break
        else:
            ret, buffer = cv2.imencode('.jpg', frame)
            frame = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')







if __name__ == "__main__":
    # initial log & default status ------------------------------------------
    log_message("info", "Drone web application started")
    drone_status.update(
        {
            "flight_mode": "STANDBY",
            "gps": get_next_gps(),  # first GPS point
        }
    )

    # run -------------------------------------------------------------------
    app.run(
        host="0.0.0.0",
        port=5000,
        threaded=True,
        debug=False,
    )
