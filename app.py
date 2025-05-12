import os
import time
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import logging

# Initialize Flask app
app = Flask(__name__)

# Configuration
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload
app.config['UPLOAD_FOLDER'] = 'data/images'
app.config['LOG_FILE'] = 'data/mission.log'
app.config['SECRET_KEY'] = 'your-secret-key-here'  # Change for production!

# Ensure directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.dirname(app.config['LOG_FILE']), exist_ok=True)

# Initialize logging
logging.basicConfig(
    filename=app.config['LOG_FILE'],
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# In-memory data store (for real-time updates)
drone_status = {
    "altitude": 0.0,
    "speed": 0.0,
    "battery": 100,
    "gps": "0.0,0.0",
    "signal_strength": -50,
    "mission_time": "00:00:00",
    "flight_mode": "INIT",
    "temperature": 25.0,
    "last_update": datetime.utcnow().isoformat()
}

latest_image = None
mission_log = []


def log_message(level, message):
    """Add message to log system"""
    timestamp = datetime.utcnow().isoformat()
    entry = {
        "timestamp": timestamp,
        "level": level,
        "message": message
    }
    mission_log.append(entry)
    logging.log(getattr(logging, level.upper()), message)

    # Keep log manageable in memory
    if len(mission_log) > 1000:
        mission_log.pop(0)


@app.route('/')
def dashboard():
    """Main dashboard page"""
    return render_template(
        'index.html',
        status=drone_status,
        latest_image=latest_image,
        logs=mission_log[-100:]  # Show last 100 entries
    )


@app.route('/api/status', methods=['GET', 'POST'])
def handle_status():
    global drone_status, latest_image

    if request.method == 'POST':
        new_data = request.get_json()
        if new_data:
            drone_status.update(new_data)
            drone_status['last_update'] = datetime.utcnow().isoformat()
            log_message("info", f"Status updated: {new_data}")
        return jsonify({"success": True, "status": drone_status})

    # GET request returns current status + latest image
    return jsonify({
        **drone_status,
        "latest_image": latest_image  # add this line
    })



@app.route('/api/image', methods=['POST'])
def upload_image():
    """Endpoint for image uploads"""
    global latest_image

    if 'image' not in request.files:
        return jsonify({"success": False, "error": "No image provided"}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({"success": False, "error": "Empty filename"}), 400

    # Save the file
    filename = secure_filename(f"{int(time.time())}_{file.filename}")
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    # Store reference
    latest_image = {
        "filename": filename,
        "timestamp": datetime.utcnow().isoformat(),
        "size": os.path.getsize(filepath)
    }

    log_message("info", f"New image received: {filename}")
    return jsonify({"success": True, "image": latest_image})


@app.route('/images/<filename>')
def serve_image(filename):
    """Serve uploaded images"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/api/log', methods=['GET', 'POST'])
def handle_log():
    """Endpoint for log retrieval and additions"""
    if request.method == 'POST':
        data = request.get_json()
        if data and 'message' in data:
            level = data.get('level', 'info')
            log_message(level, data['message'])
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Invalid log data"}), 400

    # GET request returns recent logs
    return jsonify({"logs": mission_log[-100:]})


@app.route('/api/telemetry', methods=['POST'])
def telemetry_endpoint():
    """Comprehensive endpoint for all drone telemetry"""
    global drone_status, latest_image

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    # Update status
    if 'status' in data:
        drone_status.update(data['status'])
        drone_status['last_update'] = datetime.utcnow().isoformat()

    # Handle image if included (as base64)
    if 'image' in data and data['image']:
        try:
            import base64
            from io import BytesIO
            from PIL import Image

            img_data = data['image'].split(',')[1]  # Remove data:image/... prefix
            img = Image.open(BytesIO(base64.b64decode(img_data)))
            filename = f"{int(time.time())}_drone_capture.jpg"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            img.save(filepath, "JPEG", quality=85)

            latest_image = {
                "filename": filename,
                "timestamp": datetime.utcnow().isoformat(),
                "size": os.path.getsize(filepath)
            }
        except Exception as e:
            log_message("error", f"Failed to process image: {str(e)}")

    # Handle log messages
    if 'logs' in data:
        for log_entry in data['logs']:
            level = log_entry.get('level', 'info')
            log_message(level, log_entry['message'])

    return jsonify({"success": True})

@app.route('/api/log', methods=['DELETE'])
def clear_log():
    """Endpoint to clear the mission log"""
    global mission_log
    mission_log = []
    return jsonify({"success": True})

@app.route('/api/images', methods=['GET'])
def list_images():
    """Return list of uploaded images"""
    files = os.listdir(app.config['UPLOAD_FOLDER'])
    images = sorted(files, reverse=True)  # Najnowsze na początku
    return jsonify({"images": images})

@app.route('/api/images', methods=['DELETE'])
def clear_galery():
    folder = app.config['UPLOAD_FOLDER']
    for filename in os.listdir(folder):
        file_path = os.path.join(folder, filename)
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
        except Exception as e:
            log_message("error", f"Error deleting a file {file_path}: {str(e)}")
            return jsonify({"success": False, "error": f"Failed to delete: {str(e)}"}), 500

    log_message("info", "Gallery cleared")
    return jsonify({"success": True, "message": "Gallery cleared"})

if __name__ == '__main__':
    # Initialize with some data
    log_message("info", "Drone web application started")
    drone_status.update({
        "flight_mode": "STANDBY",
        "gps": "52,21"  # Example: Warsaw coordinates
    })

    # Run the server
    app.run(
        host='0.0.0.0',
        port=5000,
        threaded=True,
        debug=False  # Set to False in production!
    )