// Global variables
let socket;
let reconnectInterval = 1000;
let maxReconnectAttempts = 10;
let reconnectAttempts = 0;
let isConnected = false;
let manualImageSelected = false;

// Mission timer variables
let missionStartTime = null;
let missionTimerInterval = null;

// DOM elements
const droneImage = document.getElementById('drone-image');
const imageTimestamp = document.getElementById('image-timestamp');
const imageSize = document.getElementById('image-size');
const missionLog = document.getElementById('mission-log');
const clearGallery = document.getElementById('clear-gallery');
const clearLogBtn = document.getElementById('clear-log');

// =================== ERROR DISPLAY ==========================
function showError(message, duration = 5000) {
    const errorBox = document.getElementById('error-display');
    if (!errorBox) return;
    errorBox.textContent = message;
    errorBox.classList.remove('hidden');
    setTimeout(() => {
        errorBox.classList.add('hidden');
    }, duration);
}
// ============================================================

// =================== MISSION TIMER ==========================
function formatMissionTime(seconds) {
    const h = String(Math.floor(seconds / 3600)).padStart(2, '0');
    const m = String(Math.floor((seconds % 3600) / 60)).padStart(2, '0');
    const s = String(seconds % 60).padStart(2, '0');
    return `${h}:${m}:${s}`;
}
function startMissionTimer() {
    if (missionTimerInterval) clearInterval(missionTimerInterval);
    missionStartTime = Date.now();
    updateMissionTime();
    missionTimerInterval = setInterval(updateMissionTime, 1000);
}
function updateMissionTime() {
    if (!missionStartTime) return;
    const elapsed = Math.floor((Date.now() - missionStartTime) / 1000);
    document.getElementById('mission_time').innerText = formatMissionTime(elapsed);
}
// ============================================================

function init() {
    setupEventListeners();
    connectWebSocket();
    fetchInitialData();
    updateDroneStatus();
    updateImagePanel();
    loadGallery();
    startMissionTimer();
}

function setupEventListeners() {
    clearLogBtn.addEventListener('click', clearLogs);
    clearGallery.addEventListener('click', clearGal);

    window.addEventListener('resize', () => {
        if (droneImage.src && droneImage.src.includes('/images/')) {
            const currentSrc = droneImage.src;
            droneImage.src = '';
            droneImage.src = currentSrc;
        }
    });
}

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
    const host = window.location.host;
    const wsUrl = `${protocol}${host}/ws`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log('WebSocket connected');
        isConnected = true;
        reconnectAttempts = 0;
        updateConnectionStatus(true);
    };

    socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        processIncomingData(data);
    };

    socket.onclose = () => {
        console.log('WebSocket disconnected');
        isConnected = false;
        updateConnectionStatus(false);
        attemptReconnect();
    };

    socket.onerror = (error) => {
        console.error('WebSocket error:', error);
        isConnected = false;
        updateConnectionStatus(false);
        showError('WebSocket connection error'+error);
    };
}

function attemptReconnect() {
    if (reconnectAttempts < maxReconnectAttempts) {
        reconnectAttempts++;
        console.log(`Attempting to reconnect (${reconnectAttempts}/${maxReconnectAttempts})...`);
        setTimeout(connectWebSocket, reconnectInterval);
    } else {
        console.error('Max reconnection attempts reached');
        showError('Max reconnection attempts reached');
    }
}

function updateConnectionStatus(connected) {
    // Optional visual indicator
}

function fetchInitialData() {
    fetch('/api/status')
        .then(response => response.json())
        .then(data => updateDroneStatus(data))
        .catch(error => {
            console.error('Error fetching initial status:', error);
            addLogEntry('error', `Failed to fetch initial status: ${error.message}`);
            showError(`Failed to fetch status: ${error.message}`);
        });

    fetch('/api/log')
        .then(response => response.json())
        .then(data => updateLogDisplay(data.logs))
        .catch(error => {
            console.error('Error fetching initial logs:', error);
            addLogEntry('error', `Failed to fetch initial logs: ${error.message}`);
            showError(`Failed to fetch logs: ${error.message}`);
        });
}

function processIncomingData(data) {
    if (data.status) updateDroneStatus(data.status);
    if (data.image) updateImageDisplay(data.image);
    if (data.logs) updateLogDisplay(data.logs);
    if (data.log) addLogEntry(data.log.level, data.log.message);
}

function updateFlightStatusIndicator(flightMode) {
    const indicator = document.getElementById('flight-status-indicator');
    if (!indicator) return;
    if (flightMode === "INIT") {
        indicator.classList.remove('active');
    } else {
        indicator.classList.add('active');
    }
}

function updateDroneStatus(status) {
    // If status is not provided, fetch from API
    if (!status) {
        fetch('/api/status')
            .then(response => response.json())
            .then(data => updateDroneStatus(data))
            .catch(error => {
                console.error('Error fetching drone status:', error);
                showError('Failed to update drone status');
            });
        return;
    }
    document.getElementById('altitude').innerText = Number(status.altitude).toFixed(2);
    document.getElementById('speed').innerText = Number(status.speed).toFixed(1);
    document.getElementById('battery_percent').innerText = `${status.battery_percent}%`;
    document.getElementById('gps_relative').innerText = status.gps_relative;
    document.getElementById('gps_global').innerText = status.gps_global;
    document.getElementById('flight_mode').innerText = status.flight_mode;
    document.getElementById('battery_voltage').innerText = `${status.battery_voltage}V`;
    document.getElementById('last_update').innerText = status.last_update;
    updateFlightStatusIndicator(status.flight_mode);
}

setInterval(() => updateDroneStatus(), 800);

function updateImagePanel() {
    fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            if (data.latest_image) {
                droneImage.src = `/images/${data.latest_image.filename}`;
                imageTimestamp.textContent = `Uploaded: ${new Date(data.latest_image.timestamp).toLocaleString()}`;
                imageSize.textContent = `Size: ${(data.latest_image.size / 1024).toFixed(2)} KB`;
            }
        })
        .catch(error => {
            console.error('Error updating image panel:', error);
            showError('Failed to update image panel');
        });
}
setInterval(updateImagePanel, 6000);
setInterval(loadGallery, 6000);

function loadGallery() {
    fetch('/api/images')
        .then(response => response.json())
        .then(data => {
            const gallery = document.getElementById('gallery-container');
            gallery.innerHTML = '';
            data.images.forEach(filename => {
                const img = document.createElement('img');
                img.src = `/images/${filename}`;
                img.className = 'thumbnail';
                img.alt = filename;
                img.addEventListener('click', () => {
                    droneImage.src = `/images/${filename}`;
                    manualImageSelected = true;
                    fetch(`/images/${filename}`, { method: 'HEAD' })
                        .then(response => {
                            const size = response.headers.get('content-length');
                            const lastModified = response.headers.get('last-modified');
                            imageTimestamp.textContent = lastModified ? `Uploaded: ${new Date(lastModified).toLocaleString()}` : 'Uploaded: Unknown';
                            imageSize.textContent = size ? `Size: ${(size / 1024).toFixed(2)} KB` : 'Size: Unknown';
                        })
                        .catch(error => {
                            console.error('Error fetching image metadata:', error);
                            showError('Failed to fetch image metadata');
                        });
                });
                gallery.appendChild(img);
            });
        })
        .catch(error => {
            console.error('Error loading gallery:', error);
            showError('Failed to load image gallery');
        });
}

function clearLogs() {
    if (!confirm('Are you sure you want to clear the logs?')) return;
    fetch('/api/log', {method: 'DELETE'})
        .then(response => response.json())
        .then (data => {
            if (data.success) {
                missionLog.innerHTML = '';

            }
        })
        .catch(error => {
            console.error('Error clearing logs:', error);
            showError('Failed to clear logs');

        });
}

function clearGal() {
    if (!confirm ('Are you sure you want to clear the image gallery?')) return;
    fetch('/api/images', {method: 'DELETE'})
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                document.getElementById('gallery-container').innerHTML = '';
                droneImage.src = 'static/placeholder.png';
                imageTimestamp.textContent = 'no image recived';
                imageSize.textContent = '-';
            }
        })
        .catch(error => {
            console.error('Error clearing gallery:', error);
            showError('Failed to clear image gallery');

        });
}

function updateLogDisplay(logs) {
    if (!logs || !Array.isArray(logs)) return;
    missionLog.innerHTML = '';
    logs.forEach(log => addLogEntry(log.level, log.message, log.timestamp));
}

function addLogEntry(level, message, timestamp) {
    if (!missionLog) return;
    const entry = document.createElement('div');
    entry.className = `log-entry log-${level.toLowerCase()}`;
    const ts = timestamp || new Date().toISOString();

    // Create timestamp span
    const timestampSpan = document.createElement('span');
    timestampSpan.className = 'log-timestamp';
    timestampSpan.textContent = new Date(ts).toLocaleTimeString();

    // Create message span
    const messageSpan = document.createElement('span');
    messageSpan.textContent = message;

    // Append to entry
    entry.appendChild(timestampSpan);
    entry.appendChild(messageSpan);
    missionLog.appendChild(entry);
    missionLog.scrollTop = missionLog.scrollHeight;
}

function updateImageDisplay(image) {
    if (!image || !image.filename) return;
    droneImage.src = `/images/${image.filename}`;
    imageTimestamp.textContent = `Uploaded: ${new Date(image.timestamp).toLocaleString()}`;
    imageSize.textContent = `Size: ${(image.size / 1024).toFixed(2)} KB`;
}

document.addEventListener('DOMContentLoaded', init);
