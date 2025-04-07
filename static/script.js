// Global variables
let socket;
let reconnectInterval = 1000;
let maxReconnectAttempts = 10;
let reconnectAttempts = 0;
let isConnected = false;

// DOM elements
const statusTable = document.querySelector('#status-table tbody');
const droneImage = document.getElementById('drone-image');
const imageTimestamp = document.getElementById('image-timestamp');
const imageSize = document.getElementById('image-size');
const missionLog = document.getElementById('mission-log');
const connectionStatus = document.getElementById('connection-status');
const refreshLogBtn = document.getElementById('refresh-log');
const clearLogBtn = document.getElementById('clear-log');

// Initialize the application
function init() {
    setupEventListeners();
    connectWebSocket();
    fetchInitialData();
}

// Set up event listeners
function setupEventListeners() {
    refreshLogBtn.addEventListener('click', fetchLogs);
    clearLogBtn.addEventListener('click', clearLogs);

    // Handle window resize for image display
    window.addEventListener('resize', () => {
        if (droneImage.src && droneImage.src.includes('/images/')) {
            // Force image refresh to handle responsive sizing
            const currentSrc = droneImage.src;
            droneImage.src = '';
            droneImage.src = currentSrc;
        }
    });
}

// WebSocket connection
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
    };
}

function attemptReconnect() {
    if (reconnectAttempts < maxReconnectAttempts) {
        reconnectAttempts++;
        console.log(`Attempting to reconnect (${reconnectAttempts}/${maxReconnectAttempts})...`);
        setTimeout(connectWebSocket, reconnectInterval);
    } else {
        console.error('Max reconnection attempts reached');
    }
}

function updateConnectionStatus(connected) {
    connectionStatus.textContent = connected ? 'Connected' : 'Disconnected';
    connectionStatus.className = connected ? 'connection-status connected' : 'connection-status';
}

// Fetch initial data on page load
function fetchInitialData() {
    fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            updateStatusTable(data);
        })
        .catch(error => {
            console.error('Error fetching initial status:', error);
            addLogEntry('error', `Failed to fetch initial status: ${error.message}`);
        });

    fetch('/api/log')
        .then(response => response.json())
        .then(data => {
            updateLogDisplay(data.logs);
        })
        .catch(error => {
            console.error('Error fetching initial logs:', error);
            addLogEntry('error', `Failed to fetch initial logs: ${error.message}`);
        });
}

// Process incoming data from WebSocket or API
function processIncomingData(data) {
    if (data.status) {
        updateStatusTable(data.status);
    }

    if (data.image) {
        updateImageDisplay(data.image);
    }

    if (data.logs) {
        updateLogDisplay(data.logs);
    }

    if (data.log) {
        addLogEntry(data.log.level, data.log.message);
    }
}

// Update status table
function updateStatusTable(status) {
    statusTable.innerHTML = '';

    for (const [key, value] of Object.entries(status)) {
        if (key === 'last_update') continue;

        const row = document.createElement('tr');

        const paramCell = document.createElement('td');
        paramCell.textContent = formatParameterName(key);
        row.appendChild(paramCell);

        const valueCell = document.createElement('td');
        valueCell.textContent = formatParameterValue(key, value);
        row.appendChild(valueCell);

        const updateCell = document.createElement('td');
        updateCell.textContent = formatTimestamp(status.last_update || new Date().toISOString());
        row.appendChild(updateCell);

        statusTable.appendChild(row);
    }
}

function formatParameterName(name) {
    return name.split('_').map(word =>
        word.charAt(0).toUpperCase() + word.slice(1)
    ).join(' ');
}

function formatParameterValue(key, value) {
    switch (key) {
        case 'altitude':
            return `${value.toFixed(2)} m`;
        case 'speed':
            return `${value.toFixed(1)} m/s`;
        case 'battery':
            return `${value}%`;
        case 'temperature':
            return `${value}°C`;
        case 'signal_strength':
            return `${value} dBm`;
        default:
            return value;
    }
}

function formatTimestamp(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleTimeString();
}

// Update image display
function updateImageDisplay(imageData) {
    if (imageData.filename) {
        droneImage.src = `/images/${imageData.filename}`;
        imageTimestamp.textContent = formatTimestamp(imageData.timestamp);
        imageSize.textContent = formatFileSize(imageData.size);
    } else if (typeof imageData === 'string') {
        // Handle base64 images
        droneImage.src = imageData;
        imageTimestamp.textContent = new Date().toLocaleTimeString();
        imageSize.textContent = 'Unknown size';
    }
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// Log handling
function fetchLogs() {
    fetch('/api/log')
        .then(response => response.json())
        .then(data => {
            updateLogDisplay(data.logs);
            addLogEntry('info', 'Logs refreshed');
        })
        .catch(error => {
            console.error('Error fetching logs:', error);
            addLogEntry('error', `Failed to refresh logs: ${error.message}`);
        });
}

function clearLogs() {
    if (confirm('Are you sure you want to clear the mission log?')) {
        fetch('/api/log', {
            method: 'DELETE'
        })
        .then(response => {
            if (response.ok) {
                missionLog.innerHTML = '';
                addLogEntry('info', 'Mission log cleared');
            }
        })
        .catch(error => {
            console.error('Error clearing logs:', error);
            addLogEntry('error', `Failed to clear logs: ${error.message}`);
        });
    }
}

function updateLogDisplay(logs) {
    missionLog.innerHTML = '';
    logs.forEach(log => {
        addLogEntry(log.level, log.message, log.timestamp);
    });
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

// Start the application
document.addEventListener('DOMContentLoaded', init);