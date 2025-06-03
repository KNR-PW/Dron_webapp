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
const statusTable = document.getElementById('status-table'); // Fix for undefined

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
        showError('WebSocket connection error');
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
        .then(data => updateStatusTable(data))
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
    if (data.status) updateStatusTable(data.status);
    if (data.image) updateImageDisplay(data.image);
    if (data.logs) updateLogDisplay(data.logs);
    if (data.log) addLogEntry(data.log.level, data.log.message);
}

function updateStatusTable(status) {
    statusTable.innerHTML = '';
    for (const [key, value] of Object.entries(status)) {
        if (key === 'last_update') continue;

        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${formatParameterName(key)}</td>
            <td>${formatParameterValue(key, value)}</td>
            <td>${formatTimestamp(status.last_update || new Date().toISOString())}</td>
        `;
        statusTable.appendChild(row);
    }
}

function formatParameterName(name) {
    return name.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}

function formatParameterValue(key, value) {
    switch (key) {
        case 'altitude': return `${value.toFixed(2)} m`;
        case 'speed': return `${value.toFixed(1)} m/s`;
        case 'battery_percent': return `${value}%`;
        case 'battery_voltage': return `${value}V`;
        default: return value;
    }
}

function formatTimestamp(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleTimeString();
}

function updateImageDisplay(imageData) {
    try {
        if (imageData.filename) {
            droneImage.src = `/images/${imageData.filename}`;
            imageTimestamp.textContent = formatTimestamp(imageData.timestamp);
            imageSize.textContent = formatFileSize(imageData.size);
        } else if (typeof imageData === 'string') {
            droneImage.src = imageData;
            imageTimestamp.textContent = new Date().toLocaleTimeString();
            imageSize.textContent = 'Unknown size';
        }
    } catch (error) {
        showError('Error updating image display');
    }
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function fetchLogs() {
    fetch('/api/log')
        .then(response => response.json())
        .then(data => updateLogDisplay(data.logs))
        .catch(error => {
            console.error('Error fetching logs:', error);
            addLogEntry('error', `Failed to refresh logs: ${error.message}`);
            showError(`Failed to refresh logs: ${error.message}`);
        });
}
setInterval(fetchLogs, 1500);

function clearLogs() {
    if (confirm('Are you sure you want to clear the mission log?')) {
        fetch('/api/log', { method: 'DELETE' })
            .then(response => {
                if (response.ok) {
                    missionLog.innerHTML = '';
                    addLogEntry('info', 'Mission log cleared');
                }
            })
            .catch(error => {
                console.error('Error clearing logs:', error);
                addLogEntry('error', `Failed to clear logs: ${error.message}`);
                showError(`Failed to clear logs: ${error.message}`);
            });
    }
}

function clearGal() {
    if (confirm('Are you sure you want to clear the gallery?')) {
        fetch('/api/images', { method: 'DELETE' })
            .then(response => {
                if (response.ok) {
                    addLogEntry('info', 'Gallery cleared');
                    loadGallery();
                } else {
                    return response.json().then(data => {
                        throw new Error(data.message || 'Failed to clear gallery');
                    });
                }
            })
            .catch(error => {
                console.error('Error clearing gallery:', error);
                addLogEntry('error', `Failed to clear gallery: ${error.message}`);
                showError(`Failed to clear gallery: ${error.message}`);
            });
    }
}

function updateLogDisplay(logs) {
    missionLog.innerHTML = '';
    logs.forEach(log => addLogEntry(log.level, log.message, log.timestamp));
}

function addLogEntry(level, message, timestamp) {
    const logEntry = document.createElement('div');
    logEntry.className = `log-entry log-${level}`;
    const timeElement = document.createElement('span');
    timeElement.className = 'log-timestamp';
    timeElement.textContent = `[${timestamp ? formatTimestamp(timestamp) : new Date().toLocaleTimeString()}]`;
    const msgElement = document.createElement('span');
    msgElement.className = `log-${level}`;
    msgElement.textContent = message;
    logEntry.appendChild(timeElement);
    logEntry.appendChild(msgElement);
    missionLog.appendChild(logEntry);
    missionLog.scrollTop = missionLog.scrollHeight;
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

function updateDroneStatus() {
    fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            document.getElementById('altitude').innerText = data.altitude.toFixed(2);
            document.getElementById('speed').innerText = data.speed.toFixed(1);
            document.getElementById('battery_percent').innerText = `${data.battery_percent}%`;
            document.getElementById('gps_relative').innerText = data.gps_relative;
            document.getElementById('gps_global').innerText = data.gps_global;
            document.getElementById('flight_mode').innerText = data.flight_mode;
            document.getElementById('battery_voltage').innerText = `${data.battery_voltage}V`;
            document.getElementById('last_update').innerText = data.last_update;
            updateFlightStatusIndicator(data.flight_mode);
        })
        .catch(error => {
            console.error('Error fetching drone status:', error);
            showError('Failed to update drone status');
        });
}
setInterval(updateDroneStatus, 800);

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

document.addEventListener('DOMContentLoaded', init);
