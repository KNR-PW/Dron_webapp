import os
from datetime import datetime, UTC

__all__ = ["drone_status", "latest_image", "mission_log", "log_message", "ensure_upload_dirs"]

# Shared runtime state for the application

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

latest_image = None
mission_log = []


def log_message(app, level: str, message: str) -> None:
    """Append message to in‑memory log and to the app logger."""
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": level,
        "message": message,
    }
    mission_log.append(entry)

    # use Flask app logger if available
    try:
        log_func = getattr(app.logger, level.lower(), app.logger.info)
        log_func(message)
    except Exception:
        print(message)

    # keep at most 1000 entries
    if len(mission_log) > 1000:
        mission_log.pop(0)


def ensure_upload_dirs(app):
    """Ensure required directories exist and are writable (uses app.config)."""
    paths = [
        app.config.get("UPLOAD_FOLDER", "data/images"),
        os.path.dirname(app.config.get("LOG_FILE", "data/mission.log")) or ".",
    ]
    for path in paths:
        os.makedirs(path, exist_ok=True)
        # Test writability
        test_file = os.path.join(path, ".write_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)

