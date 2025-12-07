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
import base64
from typing import Any, Dict, Optional

# Create Flask app and basic configuration
app = Flask(__name__)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Proxy Fix for Render / reverse proxies
if os.getenv("TRUST_PROXY", "1").lower() in ("1", "true", "yes"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)


# ------------------------------------------------------
# SECRET KEY HANDLING
# ------------------------------------------------------
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
        print("Warning: Failed to persist secret key.")
    return key


secret_key = _get_secret_key()

_is_prod = os.getenv("FLASK_DEBUG", "false").lower() != "true"
_preferred_scheme = os.getenv("PREFERRED_URL_SCHEME", "https" if _is_prod else "http")

app.config.update(
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    UPLOAD_FOLDER=os.getenv("UPLOAD_FOLDER", "data/images"),
    LOG_FILE=os.getenv("LOG_FILE", "data/mission.log"),
    SECRET_KEY=secret_key,
    SESSION_COOKIE_SAMESITE="Lax",
    REMEMBER_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_is_prod,
    REMEMBER_COOKIE_SECURE=_is_prod,
    PREFERRED_URL_SCHEME=_preferred_scheme,
)

# ------------------------------------------------------
# LOGIN MANAGER
# ------------------------------------------------------
from flask_login import LoginManager
import models

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.login"
login_manager.user_loader(models.load_user)

# ------------------------------------------------------
# FILESYSTEM PREP
# ------------------------------------------------------
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(os.path.dirname(app.config["LOG_FILE"]), exist_ok=True)

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

import state

# ------------------------------------------------------
# MQTT CONFIG
# ------------------------------------------------------
def _env_flag(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}

MQTT_ENABLED = _env_flag("MQTT_ENABLED", "1")
MQTT_HOST = os.getenv("MQTT_HOST", "f4209e15de424182b7f1f41170484e60.s1.eu.hivemq.cloud").strip()
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "Knr_web")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "Drony123")

MQTT_TOPICS = [
    t.strip()
    for t in os.getenv(
        "MQTT_TOPICS",
        "sensor/battery,robot/pose,drone/status,drone/image"
    ).split(",")
    if t.strip()
]

mqtt_client: Optional[mqtt.Client] = None


# ------------------------------------------------------
# TELEMETRY FIELD NORMALIZATION
# ------------------------------------------------------
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
        if "percent" in payload:
            updates["battery_percent"] = payload["percent"]
        if "voltage" in payload:
            updates["battery_voltage"] = payload["voltage"]

    return updates


# ------------------------------------------------------
# SNAPSHOT FOR INITIAL SOCKET CONNECTION
# ------------------------------------------------------
def _latest_snapshot() -> Dict[str, Any]:
    return {
        "status": state.drone_status,
        "image": state.latest_image,
        "logs": state.mission_log[-100:],
    }


# ------------------------------------------------------
# NORMALIZE ROS2 MESSAGE PAYLOAD
# ------------------------------------------------------
def _normalize_payload(structured: Any) -> Any:
    if isinstance(structured, dict):
        inner = structured.get("data")
        if isinstance(inner, str):
            try:
                decoded = json.loads(inner)
                if isinstance(decoded, dict):
                    return decoded
            except Exception:
                pass
    return structured


# ------------------------------------------------------
# MQTT MESSAGE HANDLER (MAIN LOGIC)
# ------------------------------------------------------
def _handle_mqtt_payload(topic: str, payload: Any) -> None:
    original_payload = payload
    structured = _normalize_payload(payload)

    # TELEMETRY UPDATE
    if isinstance(structured, dict):
        updates = _extract_status_updates(topic, structured)
    else:
        updates = {}

    if updates:
        state.drone_status.update(updates)
        state.drone_status["last_update"] = datetime.now(UTC).isoformat()

    # ------------------------------------------------------
    # IMAGE HANDLING
    # topic: "drone/image"
    # ------------------------------------------------------
    if topic.endswith("image") and isinstance(structured, dict):
        b64_data = structured.get("data")
        filename = structured.get("filename", "latest.jpg")

        if b64_data:
            try:
                raw = base64.b64decode(b64_data)

                save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                with open(save_path, "wb") as f:
                    f.write(raw)

                state.latest_image = {
                    "filename": filename,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "size": len(raw),
                }

                socketio.emit("telemetry", {"image": state.latest_image})

            except Exception as e:
                app.logger.error(f"Failed to decode or save image: {e}")

    # ------------------------------------------------------
    # LOGGING OF MESSAGE
    # ------------------------------------------------------
    log_entry = None
    if isinstance(original_payload, dict):
        log_message = original_payload.get("log") or original_payload.get("message")
        if log_message:
            level = original_payload.get("level", "info")
            state.log_message(app, level, f"{topic}: {log_message}")
            log_entry = state.mission_log[-1]
    elif original_payload:
        state.log_message(app, "info", f"{topic}: {original_payload}")
        log_entry = state.mission_log[-1]

    emit_payload = {"topic": topic, "payload": original_payload}
    if updates:
        emit_payload["status"] = state.drone_status
    if log_entry:
        emit_payload["log"] = log_entry

    socketio.emit("telemetry", emit_payload)


# ------------------------------------------------------
# MQTT CALLBACKS
# ------------------------------------------------------
def _on_mqtt_message(client, userdata, msg):
    raw = msg.payload
    decoded: Any = raw

    try:
        decoded = raw.decode("utf-8")
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
    app.logger.info(f"[MQTT] Connected with code {rc}")
    if rc != 0:
        return
    for topic in MQTT_TOPICS:
        client.subscribe(topic)
        app.logger.info(f"[MQTT] Subscribed to {topic}")


# ------------------------------------------------------
# START MQTT BRIDGE
# ------------------------------------------------------
def _start_mqtt_bridge() -> None:
    global mqtt_client

    if not MQTT_ENABLED:
        app.logger.info("MQTT_DISABLED")
        return
    if not MQTT_HOST:
        app.logger.warning("MQTT_HOST empty → MQTT disabled")
        return

    mqtt_client = mqtt.Client()

    try:
        mqtt_client.tls_set(tls_version=ssl.PROTOCOL_TLS)
    except Exception as exc:
        app.logger.warning(f"MQTT TLS configuration failed: {exc}")

    if MQTT_USERNAME:
        mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    mqtt_client.on_connect = _on_mqtt_connect
    mqtt_client.on_message = _on_mqtt_message

    try:
        mqtt_client.connect(MQTT_HOST, MQTT_PORT)
        mqtt_client.loop_start()
        app.logger.info("MQTT bridge running...")
    except Exception as exc:
        app.logger.error(f"Failed to start MQTT client: {exc}")


_start_mqtt_bridge()


# ------------------------------------------------------
# SOCKET.IO CLIENT CONNECTION
# ------------------------------------------------------
@socketio.on("connect")
def handle_socket_connect():
    emit("telemetry", _latest_snapshot())


# ------------------------------------------------------
# MAIN ENTRYPOINT
# ------------------------------------------------------
if __name__ == "__main__":
    try:
        state.ensure_upload_dirs(app)
    except Exception as e:
        app.logger.error(f"Startup failed: {e}")
        sys.exit(1)

    state.log_message(app, "info", "Drone web app started")

    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    socketio.run(app, host="0.0.0.0", port=port, debug=debug)
