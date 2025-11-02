# Use slim base for better compatibility with opencv-python-headless
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps required by Pillow/OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Runtime defaults (override via -e / env on your platform)
ENV UPLOAD_FOLDER=/var/data/images \
    LOG_FILE=/var/data/mission.log \
    FLASK_DEBUG=false \
    TRUST_PROXY=1 \
    PREFERRED_URL_SCHEME=https

# Ensure data dirs exist in container
RUN mkdir -p /var/data/images && touch /var/data/mission.log

EXPOSE 5000

# Use gunicorn for production
CMD ["sh", "-c", "gunicorn -w 2 -k gthread -b 0.0.0.0:${PORT:-5000} app:app"]
