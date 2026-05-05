import paho.mqtt.client as mqtt
import json
import logging
from datetime import datetime, timezone, timedelta
from colorama import init, Fore, Style

# Khởi tạo colorama
init(autoreset=True)

# Cấu hình Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Cấu hình MQTT
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
TOPIC_CONTROL = "classroom/control"
TOPIC_STATUS = "classroom/status"

def get_vietnam_time():
    """Lấy thời gian hiện tại theo múi giờ Việt Nam (GMT+7)."""
    tz = timezone(timedelta(hours=7))
    return datetime.now(tz).isoformat()

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info("Actuator connected to MQTT Broker!")
        client.subscribe(TOPIC_CONTROL)
        logger.info(f"Subscribed to topic: {TOPIC_CONTROL}")
    else:
        logger.error(f"Connection failed with code {rc}")

def on_message(client, userdata, msg):
    try:
        # Giải mã JSON từ payload
        payload = json.loads(msg.payload.decode())
        device = payload.get("device", "unknown")
        command = payload.get("command", "unknown")
        
        # Xử lý lệnh
        status_msg = ""
        color = Fore.WHITE
        
        if device == "light":
            if command == "ON":
                status_msg = "Đèn đã BẬT"
                color = Fore.YELLOW
            else:
                status_msg = "Đèn đã TẮT"
                color = Fore.WHITE
        elif device == "ac":
            if command == "ON":
                status_msg = "Điều hòa đã BẬT"
                color = Fore.GREEN
            else:
                status_msg = "Điều hòa đã TẮT"
                color = Fore.RED
        else:
            status_msg = f"Thiết bị {device} nhận lệnh {command}"

        # In ra console có màu
        print(f"{color}{Style.BRIGHT}[ACTUATOR] {status_msg}")
        
        # Gửi phản hồi (Feedback)
        feedback = {
            "device": device,
            "state": command,
            "timestamp": get_vietnam_time()
        }
        client.publish(TOPIC_STATUS, json.dumps(feedback))
        logger.info(f"Published feedback to {TOPIC_STATUS}")

    except Exception as e:
        logger.error(f"Error processing message: {e}")

def main():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
    except Exception as e:
        logger.error(f"Could not connect to MQTT Broker: {e}")
        return

    logger.info("Starting Actuator Simulator... (Press Ctrl+C to stop)")
    client.loop_forever()

if __name__ == "__main__":
    main()
