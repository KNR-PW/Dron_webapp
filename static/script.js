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
const statusTable = document.querySelector('#status-table tbody');
const droneImage = document.getElementById('drone-image');
const imageTimestamp = document.getElementById('image-timestamp');
const imageSize = document.getElementById('image-size');
const missionLog = document.getElementById('mission-log');
const connectionStatus = document.getElementById('connection-status');

const clearGallery = document.getElementById('clear-gallery');
const clearLogBtn = document.getElementById('clear-log');

// =================== MISSION TIMER ==========================
function formatMissionTime(seconds) {
    const h = String(Math.floor(seconds / 3600)).padStart(2, '0');
    const m = String(Math.floor((seconds % 3600) / 60)).padStart(2, '0');
    const s = String(seconds % 60).padStart(2, '0');
    return `${h}:${m}:${s}`;
}

// Start mission timer (called on page load)
function startMissionTimer() {
    if (missionTimerInterval) clearInterval(missionTimerInterval);
    missionStartTime = Date.now();
    updateMissionTime(); // od razu ustaw 00:00:00

    missionTimerInterval = setInterval(updateMissionTime, 1000);
}

function updateMissionTime() {
    if (!missionStartTime) return;
    const elapsed = Math.floor((Date.now() - missionStartTime) / 1000);
    document.getElementById('mission_time').innerText = formatMissionTime(elapsed);
}
// ============================================================

// Initialize the application
function init() {
    setupEventListeners();
    connectWebSocket();
    fetchInitialData();
    updateDroneStatus();
    updateImagePanel();
    loadGallery();
    restartVideo();
    startMissionTimer(); // Start the mission timer on page load
}

// Set up event listeners
function setupEventListeners() {

    clearLogBtn.addEventListener('click', clearLogs);
    clearGallery.addEventListener('click', clearGal);

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
            // addLogEntry('info', 'Logs refreshed');
        })
        .catch(error => {
            console.error('Error fetching logs:', error);
            addLogEntry('error', `Failed to refresh logs: ${error.message}`);
        });
}

setInterval(fetchLogs, 5000); // Fetch logs every 5 seconds

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

function clearGal() {
    if (confirm('Are you sure you want to clear the gallery?')){
        fetch('/api/images',{
            method: 'DELETE'
        })
            .then(response => {
                if (response.ok) {
                    addLogEntry('info', 'Gallery cleared');
                    loadGallery()
                } else{
                    return response.json().then(data => {
                        throw new Error(data.message || 'Failed to clear gallery');
                    });
                }
        })
            .catch(error => {
                console.error('Error clearing gallery:', error);
                addLogEntry('error', `Failed to clear gallery: ${error.message}`);
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
function updateFlightStatusIndicator(flightMode) {
    const indicator = document.getElementById('flight-status-indicator');
    if (!indicator) return;

    if (flightMode === "INIT") {
        indicator.classList.remove('active'); // Czerwony
    } else {
        indicator.classList.add('active'); // Zielony
    }
}

// Funkcja do aktualizacji statusu drona
function updateDroneStatus() {
    fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            document.getElementById('altitude').innerText = data.altitude.toFixed(2);
            document.getElementById('speed').innerText = data.speed.toFixed(1);
            document.getElementById('battery').innerText = `${data.battery}%`;
            document.getElementById('gps').innerText = data.gps;
            document.getElementById('signal_strength').innerText = `${data.signal_strength} dBm`;
            // document.getElementById('mission_time').innerText = data.mission_time;
            // Mission time is now handled by frontend JS timer!
            document.getElementById('flight_mode').innerText = data.flight_mode;
            document.getElementById('temperature').innerText = `${data.temperature}°C`;
            document.getElementById('last_update').innerText = data.last_update;

            // ➡️ Dodajemy to tu:
            updateFlightStatusIndicator(data.flight_mode);
        })
        .catch(error => {
            console.error('Error fetching drone status:', error);
        });
}

// Wywołanie funkcji co 2 sekundy
setInterval(updateDroneStatus, 2000);

function updateImagePanel() {
    //if (manualImageSelected) return; // 👈 Jeśli wybrane ręcznie, nie aktualizuj!

    fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            if (data.latest_image) {
                const imageElement = document.getElementById('drone-image');
                const timestampElement = document.getElementById('image-timestamp');
                const sizeElement = document.getElementById('image-size');

                imageElement.src = `/images/${data.latest_image.filename}`;
                imageElement.alt = 'Drone Image';
                timestampElement.textContent = `Uploaded: ${new Date(data.latest_image.timestamp).toLocaleString()}`;
                sizeElement.textContent = `Size: ${(data.latest_image.size / 1024).toFixed(2)} KB`;
            }
        })
        .catch(error => console.error('Error updating image panel:', error));
}

// Call this function periodically or after an image upload
setInterval(updateImagePanel, 10000);
setInterval(loadGallery, 10000);   //USTAWIENIA CZASU WYSWIETLANIA ZDJECIA Z GALERII

function loadGallery() {
    fetch('/api/images')
        .then(response => response.json())
        .then(data => {
            const gallery = document.getElementById('gallery-container');
            gallery.innerHTML = ''; // Wyczyść stare miniaturki

            data.images.forEach(filename => {
                const img = document.createElement('img');
                img.src = `/images/${filename}`;
                img.className = 'thumbnail';
                img.alt = filename;

                // Kliknięcie zmienia duży obrazek
                img.addEventListener('click', () => {
                    const mainImage = document.getElementById('drone-image');
                    const timestampElement = document.getElementById('image-timestamp');
                    const sizeElement = document.getElementById('image-size');

                    mainImage.src = `/images/${filename}`;
                    manualImageSelected = true; // <- Użytkownik kliknął ręcznie!

                    // Pobierz metadane z prawidłowej ścieżki
                    fetch(`/images/${filename}`, { method: 'HEAD' })
                        .then(response => {
                            const size = response.headers.get('content-length');
                            const lastModified = response.headers.get('last-modified');

                            if (lastModified) {
                                const uploadedDate = new Date(lastModified);
                                timestampElement.textContent = `Uploaded: ${uploadedDate.toLocaleString()}`;
                            } else {
                                timestampElement.textContent = `Uploaded: Unknown`;
                            }

                            if (size) {
                                sizeElement.textContent = `Size: ${(size / 1024).toFixed(2)} KB`;
                            } else {
                                sizeElement.textContent = `Size: Unknown`;
                            }
                        })
                        .catch(error => {
                            console.error('Error fetching image metadata:', error);
                        });
                });
                gallery.appendChild(img);
            });
        })
        .catch(error => console.error('Error loading gallery:', error));
}

// Inicjalizacja po stronie klienta WebRTC
let peerConnection = null;
const videoElement = document.getElementById('drone-camera-view');
// Konfiguracja STUN
const config = {
  iceServers: [
    { urls: 'stun:stun.l.google.com:19302' }
  ]
};
function startCameraView() {
    peerConnection = new RTCPeerConnection(config);

    peerConnection.ontrack = function(event) {
        // Przyjmujemy strumień video (jeden track = video z drona)
        videoElement.srcObject = event.streams[0];
    };

    // Komunikacja sygnalizacyjna przez WebSocket/REST/API
    // To wymaga podpięcia do backendu, który pośredniczy między klientami
    socket.onmessage = (event) => {
        let data = JSON.parse(event.data);
        if (data.webrtc_offer) {
            peerConnection.setRemoteDescription(new RTCSessionDescription(data.webrtc_offer))
                .then(() => peerConnection.createAnswer())
                .then(answer => peerConnection.setLocalDescription(answer))
                .then(() => {
                    // Wysyłka odpowiedzi SDP do serwera
                    socket.send(JSON.stringify({webrtc_answer: peerConnection.localDescription}));
                });
        }
        if (data.ice_candidate) {
            peerConnection.addIceCandidate(new RTCIceCandidate(data.ice_candidate));
        }
    };
    // Wysyłanie własnych kandydatów
    peerConnection.onicecandidate = function(event) {
        if (event.candidate) {
            socket.send(JSON.stringify({ice_candidate: event.candidate}));
        }
    };
}

// Wywołaj funkcję, gdy strona się załaduje lub gdy użytkownik zechce podgląd
// window.addEventListener('DOMContentLoaded', startCameraView);

// Start the application
document.addEventListener('DOMContentLoaded', init);
const videoEl = document.getElementById('drone-camera-view');
function restartVideo() {
  videoEl.currentTime = 0;
  videoEl.play();
}
function startWebcamTest() {
    const video = document.getElementById('drone-camera-view');
    // Zapytanie o dostęp do kamerki i mikrofonu (tylko kamerka, jeśli 'video:true, audio:false')
    navigator.mediaDevices.getUserMedia({ video: true, audio: false })
        .then(stream => {
            video.srcObject = stream;
        })
        .catch(error => {
            alert('Błąd podczas uruchamiania kamery: ' + error);
        });
}

document.getElementById('test-webcam-btn').addEventListener('click', () => {
    startWebcamTest();
});

document.getElementById('connect-drone-btn').addEventListener('click', () => {
    startCameraView();
});

// Wywołaj funkcję automatycznie po załadowaniu strony lub z przycisku testowego
//window.addEventListener('DOMContentLoaded', startWebcamTest);

// Aktualizuj licznik misji co sekundę
setInterval(updateMissionTime, 1000);