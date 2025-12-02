import os
import sys
import logging
from datetime import datetime, UTC
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_socketio import SocketIO, emit
import paho.mqtt.client as mqtt
import ssl
import json
from typing import Any, Dict, Optional

# Create Flask app and basic configuration (moved from monolithic app.py)
app = Flask(__name__)


socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
# Respect reverse proxy headers (X-Forwarded-*) when behind a load balancer
if os.getenv("TRUST_PROXY", "1").lower() in ("1", "true", "yes"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Generate or load a persistent secret key (unless provided via env)
def _get_secret_key() -> bytes:
    env_key = os.getenv("SECRET_KEY")
    if env_key:
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
        print("Warning: Failed to persist secret key; sessions may reset on restart.")
    return key

secret_key = _get_secret_key()

# Determine environment (prod vs dev) and preferred URL scheme
_is_prod = os.getenv("FLASK_DEBUG", "false").lower() != "true"
_preferred_scheme = os.getenv("PREFERRED_URL_SCHEME", "https" if _is_prod else "http")

app.config.update(
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    UPLOAD_FOLDER=os.getenv("UPLOAD_FOLDER", "data/images"),
    LOG_FILE=os.getenv("LOG_FILE", "data/mission.log"),
    SECRET_KEY=secret_key,
    SESSION_COOKIE_SAMESITE="Lax",
    REMEMBER_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    REMEMBER_COOKIE_SECURE=False,
    PREFERRED_URL_SCHEME=_preferred_scheme,
)

if _is_prod:
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        REMEMBER_COOKIE_SECURE=True,
    )

# Initialize login manager and register user loader from models
from flask_login import LoginManager
import models

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to access this page."
# Register the user loader function implemented in models
login_manager.user_loader(models.load_user)

# Ensure runtime directories exist
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(os.path.dirname(app.config["LOG_FILE"]), exist_ok=True)

# Configure logging
logging.basicConfig(
    filename=app.config["LOG_FILE"],
    level=logging.INFO,
    format="%(asctime)s — %(levelname)s — %(message)s",
)

# Register blueprints
from auth import bp as auth_bp
from routes import bp as routes_bp

app.register_blueprint(auth_bp)
app.register_blueprint(routes_bp)

# Expose app object for WSGI servers

# Provide a small helper to ensure upload dirs using state logic
import state


def _env_flag(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


MQTT_ENABLED = _env_flag("MQTT_ENABLED", "1")
MQTT_HOST = os.getenv("MQTT_HOST", "f4209e15de424182b7f1f41170484e60.s1.eu.hivemq.cloud").strip()
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "Knr_web")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "Drony123")
MQTT_TOPICS = [t.strip() for t in os.getenv("MQTT_TOPICS", "sensor/battery,robot/pose").split(",") if t.strip()]

mqtt_client: Optional[mqtt.Client] = None


def _extract_status_updates(topic: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}
    alias_map = {
        "altitude": ("altitude", "alt"),
        "speed": ("speed", "velocity"),
        "battery_percent": ("battery_percent", "battery", "percent"),
        "battery_voltage": ("battery_voltage", "voltage"),
        "gps_relative": ("gps_relative",),
        "flight_mode": ("flight_mode", "mode"),
        "mission_time": ("mission_time",),
    }
    for target, aliases in alias_map.items():
        for alias in aliases:
            if alias in payload and payload[alias] is not None:
                updates[target] = payload[alias]
                break

    lat = payload.get("lat") or payload.get("latitude")
    lon = payload.get("lon") or payload.get("longitude")
    if lat is not None and lon is not None:
        updates["gps_global"] = f"{lat},{lon}"

    if topic.endswith("battery"):
        if "percent" in payload and "battery_percent" not in updates:
            updates["battery_percent"] = payload["percent"]
        if "voltage" in payload and "battery_voltage" not in updates:
            updates["battery_voltage"] = payload["voltage"]

    return updates


def _latest_snapshot() -> Dict[str, Any]:
    return {
        "status": state.drone_status,
        "image": state.latest_image,
        "logs": state.mission_log[-100:],
    }


def _handle_mqtt_payload(topic: str, payload: Any) -> None:
    structured = payload
    if isinstance(structured, dict):
        updates = _extract_status_updates(topic, structured)
    else:
        updates = {}

    if updates:
        state.drone_status.update(updates)
        state.drone_status["last_update"] = datetime.now(UTC).isoformat()

    log_entry = None
    if isinstance(structured, dict):
        log_message = structured.get("log") or structured.get("message")
        if log_message:
            level = structured.get("level", "info")
            state.log_message(app, level, f"{topic}: {log_message}")
            log_entry = state.mission_log[-1] if state.mission_log else None
    elif structured:
        state.log_message(app, "info", f"{topic}: {structured}")
        log_entry = state.mission_log[-1] if state.mission_log else None

    emit_payload: Dict[str, Any] = {"topic": topic, "payload": structured}
    if updates:
        emit_payload["status"] = state.drone_status
    if log_entry:
        emit_payload["log"] = log_entry

    socketio.emit("telemetry", emit_payload)


def _on_mqtt_message(client, userdata, msg):
    raw_payload: Any = msg.payload
    decoded: Any = raw_payload
    try:
        decoded = raw_payload.decode("utf-8")
    except Exception:
        pass

    if isinstance(decoded, str):
        try:
            decoded = json.loads(decoded)
        except Exception:
            pass

    if not isinstance(decoded, (dict, list)) and isinstance(decoded, bytes):
        decoded = decoded.decode(errors="ignore")

    _handle_mqtt_payload(msg.topic, decoded)


def _on_mqtt_connect(client, userdata, flags, rc):
    status_text = mqtt.error_string(rc)
    app.logger.info("[MQTT] Connected with result %s (%s)", rc, status_text)
    if rc != 0:
        return
    for topic in MQTT_TOPICS:
        client.subscribe(topic)
        app.logger.info("[MQTT] Subscribed to %s", topic)


def _start_mqtt_bridge() -> None:
    global mqtt_client
    if not MQTT_ENABLED:
        app.logger.info("MQTT bridge disabled via MQTT_ENABLED flag")
        return
    if not MQTT_HOST:
        app.logger.warning("MQTT bridge disabled because MQTT_HOST is empty")
        return

    mqtt_client = mqtt.Client()
    try:
        mqtt_client.tls_set(tls_version=ssl.PROTOCOL_TLS)
    except Exception as exc:
        app.logger.warning("MQTT TLS configuration failed: %s", exc)
    if MQTT_USERNAME:
        mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    mqtt_client.on_connect = _on_mqtt_connect
    mqtt_client.on_message = _on_mqtt_message

    try:
        mqtt_client.connect(MQTT_HOST, MQTT_PORT)
        mqtt_client.loop_start()
        app.logger.info("MQTT bridge started (host=%s port=%s)", MQTT_HOST, MQTT_PORT)
    except Exception as exc:
        app.logger.error("Failed to start MQTT client: %s", exc)


_start_mqtt_bridge()


@socketio.on("connect")
def handle_socket_connect():
    emit("telemetry", _latest_snapshot())


if __name__ == "__main__":
    # Allow overriding using env vars
    app.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER", app.config.get("UPLOAD_FOLDER", "data/images"))
    app.config["LOG_FILE"] = os.getenv("LOG_FILE", app.config.get("LOG_FILE", "data/mission.log"))
    if os.getenv("SECRET_KEY"):
        app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

    try:
        state.ensure_upload_dirs(app)
    except Exception as e:
        app.logger.error(f"Startup failed: {e}")
        sys.exit(1)

    state.log_message(app, "info", "Drone web application started")

    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    socketio.run(app, host="0.0.0.0", port=port, debug=debug)
