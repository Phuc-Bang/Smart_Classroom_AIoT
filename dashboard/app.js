// Cấu hình MQTT
const MQTT_WS_URL = "ws://localhost:9001";
const TOPIC_SENSORS = "classroom/A203/sensors";
const TOPIC_ANOMALY = "classroom/anomaly";

// Cấu hình Backend
const BACKEND_URL = "http://localhost:8000";

// Trạng thái hiện tại
let currentStatus = {
    light: "OFF",
    ac: "OFF"
};

// --- Khởi tạo Chart.js ---
const ctx = document.getElementById('tempChart').getContext('2d');
const tempChart = new Chart(ctx, {
    type: 'line',
    data: {
        labels: [],
        datasets: [
            {
                label: 'Temperature (°C)',
                data: [],
                borderColor: '#e74c3c',
                backgroundColor: 'rgba(231, 76, 60, 0.1)',
                tension: 0.4,
                yAxisID: 'y'
            },
            {
                label: 'Humidity (%)',
                data: [],
                borderColor: '#3498db',
                backgroundColor: 'rgba(52, 152, 219, 0.1)',
                tension: 0.4,
                yAxisID: 'y1'
            }
        ]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
            y: { type: 'linear', position: 'left' },
            y1: { type: 'linear', position: 'right', grid: { drawOnChartArea: false } }
        }
    }
});

// --- Kết nối MQTT ---
const client = mqtt.connect(MQTT_WS_URL);

client.on('connect', () => {
    addLog("Connected to MQTT via WebSocket");
    client.subscribe([TOPIC_SENSORS, TOPIC_ANOMALY]);
});

client.on('message', (topic, message) => {
    const payload = JSON.parse(message.toString());
    
    if (topic === TOPIC_SENSORS) {
        updateUI(payload);
    } else if (topic === TOPIC_ANOMALY) {
        showAnomaly(payload);
    }
});

// --- Cập nhật giao diện ---
function updateUI(data) {
    // 1. Cập nhật Text
    document.getElementById('temp-value').textContent = `${data.temperature}°C`;
    document.getElementById('people-value').textContent = `People: ${data.people_count}`;
    
    // 2. Cập nhật Digital Twin (Màu sắc)
    const roomWall = document.getElementById('room-wall');
    const acUnit = document.getElementById('ac-unit');
    const light1 = document.getElementById('light1');
    const light2 = document.getElementById('light2');

    // AC
    if (data.ac_state === "ON") {
        acUnit.classList.add('ac-on');
        document.getElementById('ac-status-text').textContent = "ON";
        document.getElementById('ac-status-text').className = "badge bg-info";
        currentStatus.ac = "ON";
    } else {
        acUnit.classList.remove('ac-on');
        document.getElementById('ac-status-text').textContent = "OFF";
        document.getElementById('ac-status-text').className = "badge bg-secondary";
        currentStatus.ac = "OFF";
    }

    // Lights
    if (data.light_state === "ON") {
        light1.classList.add('light-on');
        light2.classList.add('light-on');
        document.getElementById('light-status-text').textContent = "ON";
        document.getElementById('light-status-text').className = "badge bg-warning text-dark";
        currentStatus.light = "ON";
    } else {
        light1.classList.remove('light-on');
        light2.classList.remove('light-on');
        document.getElementById('light-status-text').textContent = "OFF";
        document.getElementById('light-status-text').className = "badge bg-secondary";
        currentStatus.light = "OFF";
    }

    // 3. Cập nhật Biểu đồ
    const now = new Date().toLocaleTimeString();
    tempChart.data.labels.push(now);
    tempChart.data.datasets[0].data.push(data.temperature);
    tempChart.data.datasets[1].data.push(data.humidity);

    if (tempChart.data.labels.length > 20) {
        tempChart.data.labels.shift();
        tempChart.data.datasets[0].data.shift();
        tempChart.data.datasets[1].data.shift();
    }
    tempChart.update('none'); // Update without animation for performance
}

function showAnomaly(data) {
    const alertBox = document.getElementById('alert-box');
    const roomWall = document.getElementById('room-wall');
    const reasonText = document.getElementById('anomaly-reason');

    if (data.is_anomaly) {
        alertBox.classList.remove('d-none');
        roomWall.classList.add('anomaly-border');
        reasonText.textContent = `Reason: ${data.reason}`;
        addLog(`⚠️ ANOMALY: ${data.reason}`, "danger");
        
        // Tự động ẩn sau 10 giây
        setTimeout(() => {
            alertBox.classList.add('d-none');
            roomWall.classList.remove('anomaly-border');
        }, 10000);
    }
}

// --- Điều khiển thiết bị ---
document.getElementById('btn-toggle-light').addEventListener('click', () => {
    const nextCommand = currentStatus.light === "ON" ? "OFF" : "ON";
    sendCommand("light", nextCommand);
});

document.getElementById('btn-toggle-ac').addEventListener('click', () => {
    const nextCommand = currentStatus.ac === "ON" ? "OFF" : "ON";
    sendCommand("ac", nextCommand);
});

async function sendCommand(device, command) {
    try {
        const response = await fetch(`${BACKEND_URL}/api/control`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device, command, room_id: "room_A203" })
        });
        const result = await response.json();
        addLog(`Sent command: ${device} -> ${command}`);
    } catch (error) {
        addLog(`Error sending command: ${error}`, "danger");
    }
}

function addLog(msg, type = "success") {
    const container = document.getElementById('log-container');
    const div = document.createElement('div');
    div.className = `text-${type}`;
    div.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}
