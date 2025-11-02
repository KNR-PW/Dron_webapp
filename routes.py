from flask import Blueprint, render_template, request, jsonify, send_from_directory, abort, Response, current_app
from flask_login import login_required
from werkzeug.utils import secure_filename
from PIL import Image
from io import BytesIO
import os
import time
import base64

import state

bp = Blueprint('routes', __name__)


@bp.route('/')
@login_required
def dashboard():
    return render_template(
        'index.html',
        status=state.drone_status,
        latest_image=state.latest_image,
        logs=state.mission_log[-100:],
    )


@bp.route('/api/status', methods=['GET', 'POST'])
@login_required
def handle_status():
    if request.method == 'POST':
        new_data = request.get_json(silent=True)
        if new_data:
            state.drone_status.update(new_data)
            state.drone_status['last_update'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        return jsonify({'success': True, 'status': state.drone_status})

    return jsonify({**state.drone_status, 'latest_image': state.latest_image})


@bp.route('/api/image', methods=['POST'])
@login_required
def upload_image():
    if 'image' not in request.files:
        return jsonify({'success': False, 'error': 'No image provided'}), 400
    file = request.files['image']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Empty filename'}), 400
    filename = secure_filename(f"{int(time.time())}_{file.filename}")
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    state.latest_image = {
        'filename': filename,
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'size': os.path.getsize(filepath),
    }
    state.log_message(current_app, 'info', f'New image received: {filename}')
    return jsonify({'success': True, 'image': state.latest_image})


@bp.route('/images/<path:filename>')
@login_required
def serve_image(filename):
    if '..' in filename or filename.startswith('/'):
        abort(400)
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)


@bp.route('/api/log', methods=['GET', 'POST', 'DELETE'])
@login_required
def handle_log():
    if request.method == 'POST':
        data = request.get_json(silent=True)
        if data and 'message' in data:
            level = data.get('level', 'info')
            state.log_message(current_app, level, data['message'])
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Invalid log data'}), 400

    if request.method == 'DELETE':
        state.mission_log = []
        return jsonify({'success': True})

    return jsonify({'logs': state.mission_log[-100:]})


@bp.route('/api/telemetry', methods=['POST'])
@login_required
def telemetry_endpoint():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    if 'status' in data:
        state.drone_status.update(data['status'])
        state.drone_status['last_update'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

    if 'image' in data and data['image']:
        try:
            img_data = data['image'].split(',', 1)[1]
            img = Image.open(BytesIO(base64.b64decode(img_data)))
            filename = f"{int(time.time())}_drone_capture.jpg"
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            img.save(filepath, 'JPEG', quality=85)
            state.latest_image = {
                'filename': filename,
                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'size': os.path.getsize(filepath),
            }
        except Exception as exc:
            state.log_message(current_app, 'error', f'Failed to process image: {exc}')

    if 'logs' in data:
        for log_entry in data['logs']:
            level = log_entry.get('level', 'info')
            state.log_message(current_app, level, log_entry.get('message', ''))

    return jsonify({'success': True})


@bp.route('/api/images', methods=['GET', 'DELETE'])
@login_required
def images_api():
    folder = current_app.config['UPLOAD_FOLDER']
    if request.method == 'DELETE':
        errors = []
        for filename in os.listdir(folder):
            try:
                os.remove(os.path.join(folder, filename))
            except Exception as exc:
                errors.append(f"{filename}: {exc}")
        if errors:
            state.log_message(current_app, 'error', f'Image delete errors: {errors}')
            return jsonify({'success': False, 'error': errors}), 500
        state.log_message(current_app, 'info', 'Gallery cleared')
        return jsonify({'success': True})
    images = sorted(os.listdir(folder), reverse=True)
    return jsonify({'images': images})


@bp.route('/healthz')
def healthz():
    return jsonify({'status': 'ok'})


# --- Video feed (best-effort; Render likely doesn't provide camera) ---
try:
    import cv2
    _CV2_AVAILABLE = True
except Exception:
    cv2 = None
    _CV2_AVAILABLE = False


def generate_frames():
    if not _CV2_AVAILABLE:
        raise RuntimeError('OpenCV is not available in the environment')
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        raise RuntimeError('Camera access unavailable')
    while True:
        success, frame = camera.read()
        if not success:
            break
        ret, buffer = cv2.imencode('.jpg', frame)
        if not ret:
            break
        frame_bytes = buffer.tobytes()
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n")


@bp.route('/video_feed')
@login_required
def video_feed():
    if not _CV2_AVAILABLE:
        state.log_message(current_app, 'error', 'OpenCV nie jest dostępne w środowisku')
        return jsonify({'success': False, 'error': 'OpenCV nie jest dostępne na serwerze'}), 503
    try:
        return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')
    except Exception as exc:
        state.log_message(current_app, 'error', f'Błąd strumienia wideo: {exc}')
        return jsonify({'success': False, 'error': str(exc)}), 503

