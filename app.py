import os
import sys
import logging
from datetime import datetime, UTC
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

# Create Flask app and basic configuration (moved from monolithic app.py)
app = Flask(__name__)

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

    app.run(host="0.0.0.0", port=port, threaded=True, debug=debug)
