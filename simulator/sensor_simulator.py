import time
import json
import random
import logging
from datetime import datetime, timezone, timedelta
import paho.mqtt.client as mqtt

# Cấu hình Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Cấu hình MQTT
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "classroom/A203/sensors"
DEVICE_ID = "room_A203"
INTERVAL = 5 # giây

# Trạng thái ban đầu
state = {
    "people_count": 0,
    "temperature": 26.0,
    "humidity": 60.0
}

def get_vietnam_time():
    """Lấy thời gian hiện tại theo múi giờ Việt Nam (GMT+7)."""
    tz = timezone(timedelta(hours=7))
    return datetime.now(tz)

def generate_sensor_data():
    """Sinh dữ liệu cảm biến dựa trên logic thời gian thực và xác suất."""
    global state
    now = get_vietnam_time()
    hour = now.hour
    
    # 1. Mô phỏng số lượng người (people_count)
    if 8 <= hour < 12 or 13 <= hour < 17:
        target_people = random.randint(15, 25)
    elif 12 <= hour < 13:
        target_people = random.randint(0, 5)
    elif 17 <= hour < 22:
        target_people = random.randint(0, 10)
    else:
        target_people = 0
    
    # Thay đổi từ từ ±2 người
    diff = target_people - state["people_count"]
    change = max(-2, min(2, diff))
    state["people_count"] += change
    state["people_count"] = max(0, state["people_count"])

    # 2. Mô phỏng nhiệt độ (temperature) 24-34°C theo chu kỳ ngày
    # Nhiệt độ cơ bản dựa trên giờ (đỉnh điểm lúc 14h)
    base_temp = 28 + 5 * (1 - abs(hour - 14) / 12)
    state["temperature"] = base_temp + random.uniform(-1, 1)
    
    # 5% xác suất tăng đột biến > 38°C
    is_temp_spike = random.random() < 0.05
    if is_temp_spike:
        state["temperature"] = random.uniform(38.5, 42.0)
        logger.warning("Simulating Temp Spike!")

    # 3. Mô phỏng độ ẩm (humidity) 50-80%, tương quan nghịch với nhiệt độ
    state["humidity"] = 100 - state["temperature"] * 1.5 + random.uniform(-5, 5)
    state["humidity"] = max(50, min(80, state["humidity"]))
    
    # 4. Mô phỏng ánh sáng (light_intensity)
    if 6 <= hour < 18: # Ban ngày
        light_intensity = random.uniform(200, 700)
    else: # Ban đêm
        light_intensity = random.uniform(20, 100)

    # 5. Trạng thái AC và Đèn (Logic đơn giản)
    ac_state = "ON" if (state["temperature"] > 26 and state["people_count"] > 0) else "OFF"
    light_state = "ON" if (light_intensity < 300 and state["people_count"] > 0) else "OFF"

    # 6. Điện năng tiêu thụ (power_consumption)
    power = 0.5 # Nền
    if ac_state == "ON": power += 2.0
    if light_state == "ON": power += 0.5
    power_consumption = round(power + random.uniform(0, 0.1), 2)

    # 7. Mã lỗi (error_code) - xác suất 2%
    error_code = None
    if random.random() < 0.02:
        error_code = random.choice(["ERR_TEMP_SPIKE", "ERR_HUMIDITY_DROP", "ERR_POWER_ANOMALY"])

    # Đóng gói JSON
    data = {
        "device_id": DEVICE_ID,
        "timestamp": now.isoformat(),
        "temperature": round(state["temperature"], 2),
        "humidity": round(state["humidity"], 2),
        "light_intensity": round(light_intensity, 2),
        "people_count": state["people_count"],
        "ac_state": ac_state,
        "light_state": light_state,
        "power_consumption": power_consumption,
        "error_code": error_code
    }
    return data

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info("Connected to MQTT Broker!")
    else:
        logger.error(f"Connection failed with code {rc}")

def main():
    # Sử dụng VERSION1 để tương thích với code hiện tại (paho-mqtt 2.x yêu cầu khai báo này)
    try:
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION1)
    except AttributeError:
        # Dành cho các phiên bản paho-mqtt cũ hơn 2.0
        client = mqtt.Client()
        
    client.on_connect = on_connect
    
    logger.info(f"Connecting to MQTT Broker at {MQTT_BROKER}:{MQTT_PORT}...")
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
    except Exception as e:
        logger.error(f"FATAL: Could not connect to MQTT Broker: {e}")
        return

    client.loop_start()

    try:
        logger.info("Simulator started. Entering main loop...")
        while True:
            data = generate_sensor_data()
            payload = json.dumps(data)
            result = client.publish(MQTT_TOPIC, payload)
            
            # Kiểm tra trạng thái gửi
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"Published to {MQTT_TOPIC}: {payload}")
            else:
                logger.error(f"Failed to publish message, return code: {result.rc}")
                
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        logger.info("Simulator stopping by user...")
    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}")
    finally:
        client.loop_stop()
        client.disconnect()
        logger.info("Simulator finished.")

if __name__ == "__main__":
    main()
