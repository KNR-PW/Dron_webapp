// Global variables
let socket;
let reconnectInterval = 1000;
let maxReconnectAttempts = 10;
let reconnectAttempts = 0;
let isConnected = false;
let isMqttConnected = false;
let manualImageSelected = false;

// Mission timer variables
let missionStartTime = null;
let missionTimerInterval = null;
let lastMqttMessageTime = null;
let mqttTimeoutCheck = null;

// DOM elements
const droneImage = document.getElementById('drone-image');
const imageTimestamp = document.getElementById('image-timestamp');
const imageSize = document.getElementById('image-size');
const missionLog = document.getElementById('mission-log');
const clearGallery = document.getElementById('clear-gallery');
const clearLogBtn = document.getElementById('clear-log');

// Status panel elements (cache for performance)
const statusElements = {
    altitude: document.getElementById('altitude'),
    speed: document.getElementById('speed'),
    battery_percent: document.getElementById('battery_percent'),
    battery_voltage: document.getElementById('battery_voltage'),
    gps_relative: document.getElementById('gps_relative'),
    gps_global: document.getElementById('gps_global'),
    flight_mode: document.getElementById('flight_mode'),
    last_update: document.getElementById('last_update')
};

// =================== ERROR DISPLAY ==========================
function showError(message, duration = 5000) {
    const errorBox = document.getElementById('error-display');
    if (!errorBox) return;
    errorBox.textContent = message;
    errorBox.classList.remove('hidden');
    errorBox.classList.remove('success');
    setTimeout(() => {
        errorBox.classList.add('hidden');
    }, duration);
}

function showSuccess(message, duration = 3000) {
    const errorBox = document.getElementById('error-display');
    if (!errorBox) return;
    errorBox.textContent = message;
    errorBox.classList.remove('hidden');
    errorBox.classList.add('success');
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
    startMqttMonitoring();
    updateLogCounter();
}

function startMqttMonitoring() {
    if (mqttTimeoutCheck) clearInterval(mqttTimeoutCheck);

    mqttTimeoutCheck = setInterval(() => {
        if (lastMqttMessageTime) {
            const timeSinceLastMessage = Date.now() - lastMqttMessageTime;
            const mqttTimeout = 15000; // 15 seconds

            if (timeSinceLastMessage > mqttTimeout && isMqttConnected) {
                updateMqttStatus(false);
            }
        }
    }, 5000); // Check every 5 seconds
}

function setupEventListeners() {
    if (clearLogBtn) clearLogBtn.addEventListener('click', clearLogs);
    if (clearGallery) clearGallery.addEventListener('click', clearGal);

    // Live video stream error handling
    const liveVideo = document.getElementById('live-video');
    if (liveVideo) {
        liveVideo.addEventListener('error', () => {
            console.warn('Live video stream unavailable');
            addLogEntry('warning', 'Live video stream is unavailable');
        });

        liveVideo.addEventListener('load', () => {
            console.log('Live video stream loaded');
        });
    }

    window.addEventListener('resize', () => {
        if (droneImage && droneImage.src && droneImage.src.includes('/images/')) {
            const currentSrc = droneImage.src;
            droneImage.src = '';
            droneImage.src = currentSrc;
        }
    });
}

function connectWebSocket() {
    if (socket && socket.connected) return;
    socket = io({
        transports: ['websocket', 'polling'],
        reconnectionAttempts: maxReconnectAttempts,
    });

    socket.on('connect', () => {
        console.log('Socket.IO connected');
        isConnected = true;
        reconnectAttempts = 0;
        updateConnectionStatus(true);
        addLogEntry('info', 'WebSocket connected');
    });

    socket.on('connect_error', (error) => {
        console.error('Socket.IO connect error:', error);
        addLogEntry('error', `Socket error: ${error.message}`);
        showError('Socket connection error: ' + error.message);
    });

    socket.on('disconnect', () => {
        console.log('Socket.IO disconnected');
        isConnected = false;
        updateConnectionStatus(false);
        addLogEntry('warning', 'WebSocket disconnected');
    });

    socket.on('reconnect_attempt', (attempt) => {
        reconnectAttempts = attempt;
        console.log(`Socket.IO reconnect attempt ${attempt}`);
        if (attempt % 5 === 0) {
            addLogEntry('warning', `Reconnection attempt ${attempt}`);
        }
    });

    socket.on('telemetry', (data) => {
        processIncomingData(data);
    });
}

function updateConnectionStatus(connected) {
    const indicator = document.getElementById('flight-status-indicator');
    if (!indicator) return;
    indicator.dataset.connection = connected ? 'online' : 'offline';
}

function updateMqttStatus(connected) {
    const mqttIndicator = document.getElementById('mqtt-status-indicator');
    if (!mqttIndicator) return;
    mqttIndicator.dataset.connection = connected ? 'online' : 'offline';
    isMqttConnected = connected;
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
    if (!data || typeof data !== 'object') {
        console.warn('Invalid incoming data:', data);
        return;
    }

    // Debug logging for received data
    if (data.topic || data.status || data.image) {
        console.debug('Telemetry received:', {
            hasStatus: !!data.status,
            hasImage: !!data.image,
            hasMqtt: !!(data.topic && data.payload)
        });
    }

    // Detect MQTT connection by presence of MQTT data
    if (data.topic && data.payload) {
        updateMqttStatus(true);
        lastMqttMessageTime = Date.now();
    }

    // Handle status updates with null-safe access
    if (data.status) {
        const safeStatus = sanitizeStatus(data.status);
        updateDroneStatus(safeStatus);
    }

    // Handle image updates
    if (data.image) updateImageDisplay(data.image);

    // Handle log arrays
    if (Array.isArray(data.logs)) updateLogDisplay(data.logs);

    // Handle individual log entry
    if (data.log) {
        const logLevel = data.log.level || 'info';
        const logMessage = data.log.message || JSON.stringify(data.log);
        const logTimestamp = data.log.timestamp;
        addLogEntry(logLevel, logMessage, logTimestamp);
    }

    // Handle MQTT topic/payload
    if (data.topic && data.payload) {
        const payloadStr = typeof data.payload === 'string'
            ? data.payload
            : JSON.stringify(data.payload);
        addLogEntry('mqtt', `[${data.topic}] ${payloadStr}`);
    }
}

// Sanitize status object to handle null/undefined values
function sanitizeStatus(status) {
    return {
        altitude: status.altitude ?? 0,
        speed: status.speed ?? 0,
        battery_percent: status.battery_percent ?? 0,
        battery_voltage: status.battery_voltage ?? '0V',
        gps_relative: status.gps_relative ?? '0,0',
        gps_global: status.gps_global ?? '0,0',
        flight_mode: status.flight_mode ?? 'INIT',
        last_update: status.last_update ?? new Date().toISOString()
    };
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

    // Safe number formatting helper
    const safeNumber = (val, decimals = 2) => {
        const num = parseFloat(val);
        return isNaN(num) ? '0.00' : num.toFixed(decimals);
    };

    // Safe string formatting helper
    const safeString = (val, fallback = '-') => {
        return val != null && val !== '' ? String(val) : fallback;
    };

    // Update DOM with safe values using cached elements
    if (statusElements.altitude) statusElements.altitude.innerText = safeNumber(status.altitude, 2);
    if (statusElements.speed) statusElements.speed.innerText = safeNumber(status.speed, 1);
    if (statusElements.battery_percent) {
        const batPercent = Math.min(100, Math.max(0, parseInt(status.battery_percent) || 0));
        statusElements.battery_percent.innerText = `${batPercent}%`;
    }
    if (statusElements.battery_voltage) statusElements.battery_voltage.innerText = safeString(status.battery_voltage, '0V');
    if (statusElements.gps_relative) statusElements.gps_relative.innerText = safeString(status.gps_relative, '0,0');
    if (statusElements.gps_global) statusElements.gps_global.innerText = safeString(status.gps_global, '0,0');
    if (statusElements.flight_mode) statusElements.flight_mode.innerText = safeString(status.flight_mode, 'INIT');

    if (statusElements.last_update && status.last_update) {
        try {
            statusElements.last_update.innerText = new Date(status.last_update).toLocaleTimeString();
        } catch (e) {
            statusElements.last_update.innerText = status.last_update;
        }
    }

    updateFlightStatusIndicator(status.flight_mode);
}

setInterval(() => updateDroneStatus(), 800);

function updateImagePanel() {
    // Auto-reset manual selection after 30 seconds
    if (manualImageSelected) {
        setTimeout(() => {
            manualImageSelected = false;
        }, 30000);
    }

    // Don't update if manual image is selected
    if (manualImageSelected) return;

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
            if (!gallery) return;

            gallery.innerHTML = '';

            if (!data.images || data.images.length === 0) {
                gallery.innerHTML = '<p style="color: #999; text-align: center;">No images yet</p>';
                return;
            }

            data.images.forEach(filename => {
                const img = document.createElement('img');
                img.src = `/images/${filename}`;
                img.className = 'thumbnail';
                img.alt = filename;
                img.title = filename;

                img.addEventListener('click', () => {
                    droneImage.src = `/images/${filename}`;
                    manualImageSelected = true;

                    fetch(`/images/${filename}`, { method: 'HEAD' })
                        .then(response => {
                            const size = response.headers.get('content-length');
                            const lastModified = response.headers.get('last-modified');

                            imageTimestamp.textContent = lastModified
                                ? `Uploaded: ${new Date(lastModified).toLocaleString()}`
                                : 'Uploaded: Unknown';
                            imageSize.textContent = size
                                ? `Size: ${(parseInt(size) / 1024).toFixed(2)} KB`
                                : 'Size: Unknown';
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
        .then(response => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
        })
        .then(data => {
            if (data.success) {
                if (missionLog) missionLog.innerHTML = '';
                updateLogCounter();
                addLogEntry('info', 'Mission log cleared');
                showSuccess('Logs cleared successfully');
            } else {
                showError(data.message || 'Failed to clear logs');
            }
        })
        .catch(error => {
            console.error('Error clearing logs:', error);
            showError(`Failed to clear logs: ${error.message}`);
        });
}

function clearGal() {
    if (!confirm('Are you sure you want to clear the image gallery?')) return;

    fetch('/api/images', {method: 'DELETE'})
        .then(response => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
        })
        .then(data => {
            if (data.success) {
                const gallery = document.getElementById('gallery-container');
                if (gallery) gallery.innerHTML = '';

                if (droneImage) droneImage.src = '/static/placeholder.png';
                if (imageTimestamp) imageTimestamp.textContent = 'No image received';
                if (imageSize) imageSize.textContent = '-';

                addLogEntry('info', 'Image gallery cleared');
                showSuccess('Gallery cleared successfully');
            } else {
                showError(data.message || 'Failed to clear gallery');
            }
        })
        .catch(error => {
            console.error('Error clearing gallery:', error);
            showError(`Failed to clear gallery: ${error.message}`);
        });
}

function updateLogDisplay(logs) {
    if (!logs || !Array.isArray(logs)) return;
    missionLog.innerHTML = '';
    logs.forEach(log => addLogEntry(log.level, log.message, log.timestamp));
}

function addLogEntry(level, message, timestamp) {
    if (!missionLog) return;

    try {
        const entry = document.createElement('div');
        entry.className = `log-entry log-${level.toLowerCase()}`;
        const ts = timestamp || new Date().toISOString();

        // Create timestamp span with better formatting
        const timestampSpan = document.createElement('span');
        timestampSpan.className = 'log-timestamp';
        try {
            const date = new Date(ts);
            timestampSpan.textContent = date.toLocaleTimeString('pl-PL', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
        } catch (e) {
            timestampSpan.textContent = String(ts).substring(0, 8);
        }

        // Create message span with text wrapping
        const messageSpan = document.createElement('span');
        messageSpan.textContent = message;
        messageSpan.style.wordBreak = 'break-word';

        // Append to entry
        entry.appendChild(timestampSpan);
        entry.appendChild(messageSpan);
        missionLog.appendChild(entry);

        // Auto-scroll to bottom
        missionLog.scrollTop = missionLog.scrollHeight;

        // Limit log entries to last 200 to prevent memory issues
        const maxLogEntries = 200;
        const logEntries = missionLog.querySelectorAll('.log-entry');
        if (logEntries.length > maxLogEntries) {
            for (let i = 0; i < logEntries.length - maxLogEntries; i++) {
                logEntries[i].remove();
            }
        }

        // Update log counter
        updateLogCounter();
    } catch (error) {
        console.error('Error adding log entry:', error);
    }
}

function updateLogCounter() {
    const counter = document.getElementById('log-counter');
    if (!counter || !missionLog) return;
    const count = missionLog.querySelectorAll('.log-entry').length;
    counter.textContent = `(${count})`;
}

function updateImageDisplay(image) {
    if (!image || !image.filename) return;

    try {
        droneImage.src = `/images/${image.filename}`;

        // Update timestamp safely
        if (image.timestamp) {
            try {
                const timestamp = new Date(image.timestamp).toLocaleString();
                imageTimestamp.textContent = `Uploaded: ${timestamp}`;
            } catch (e) {
                imageTimestamp.textContent = `Uploaded: ${image.timestamp}`;
            }
        }

        // Update size safely
        if (image.size) {
            const sizeKB = (image.size / 1024).toFixed(2);
            imageSize.textContent = `Size: ${sizeKB} KB`;
        }

        // Auto-scroll to latest image
        if (!manualImageSelected) {
            // Image updated automatically
        }
    } catch (error) {
        console.error('Error updating image display:', error);
        showError('Failed to update image display');
    }
}

document.addEventListener('DOMContentLoaded', init);

// Handle page visibility changes to pause/resume updates
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        console.log('Page hidden - pausing updates');
    } else {
        console.log('Page visible - resuming updates');
        // Refresh data immediately when page becomes visible
        updateDroneStatus();
        updateImagePanel();
        loadGallery();
    }
});

// Handle unload to cleanup resources
window.addEventListener('beforeunload', () => {
    if (socket) {
        socket.disconnect();
    }
    if (missionTimerInterval) {
        clearInterval(missionTimerInterval);
    }
    if (mqttTimeoutCheck) {
        clearInterval(mqttTimeoutCheck);
    }
});

