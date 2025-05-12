import requests
import time
import random
from datetime import datetime

# BASE_URL = "http://localhost:5000"
BASE_URL = "https://osadniik.pythonanywhere.com/"

def send_update():
    data = {
        "altitude": round(random.uniform(100, 200), 2),
        "speed": round(random.uniform(5, 15), 1),
        "battery": random.randint(70, 100),
        "gps": f"{round(random.uniform(47.5, 47.7), 4)},{round(random.uniform(-122.4, -122.3), 4)}",
        "signal_strength": random.randint(-80, -50),
        "flight_mode": random.choice(["AUTO", "GUIDED", "LOITER", "RTL", "INIT"]),
        "temperature": round(random.uniform(20, 35), 1)
    }

    response = requests.post(f"{BASE_URL}/api/status", json=data)
    print(f"Status update sent: {response.status_code}")

    log_level = random.choice(["info", "warning", "error"])
    log_msg = f"Simulated {log_level} message at {datetime.now().isoformat()}"
    requests.post(f"{BASE_URL}/api/log", json={"level": log_level, "message": log_msg})


if __name__ == "__main__":
    while True:
        send_update()
        time.sleep(2)  # Send updates every 2 seconds