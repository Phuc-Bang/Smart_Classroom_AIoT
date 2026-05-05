import os
import json
import logging
import threading
import asyncio
import numpy as np
import joblib
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from dateutil import parser

# --- Cấu hình ---
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# MQTT
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
TOPIC_SENSORS = "classroom/+/sensors"
TOPIC_CONTROL = "classroom/control"
TOPIC_ANOMALY = "classroom/anomaly"

# InfluxDB
INFLUXDB_URL = "http://localhost:8086"
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "smart-classroom-token")
INFLUXDB_ORG = "smartclass"
INFLUXDB_BUCKET = "smart_classroom"

# AI Model
MODEL_PATH = "model.pkl"
FEATURE_NAMES_PATH = "feature_names.pkl"

# --- Khởi tạo App ---
app = FastAPI(title="Smart Classroom AIoT Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Biến toàn cục lưu trữ trạng thái anomaly gần nhất
recent_anomalies = []
is_room_anomaly = {} # room_id -> bool

# --- InfluxDB Client ---
influx_client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
write_api = influx_client.write_api(write_options=SYNCHRONOUS)
query_api = influx_client.query_api()

# --- MQTT Client ---
mqtt_client = mqtt.Client()

def on_connect(client, userdata, flags, rc):
    logger.info(f"MQTT Connected with result code {rc}")
    client.subscribe(TOPIC_SENSORS)

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        device_id = payload.get("device_id")
        
        # Ghi vào InfluxDB
        point = Point("telemetry") \
            .tag("device_id", device_id) \
            .field("temperature", float(payload.get("temperature"))) \
            .field("humidity", float(payload.get("humidity"))) \
            .field("light_intensity", float(payload.get("light_intensity"))) \
            .field("people_count", int(payload.get("people_count"))) \
            .field("ac_state", payload.get("ac_state")) \
            .field("light_state", payload.get("light_state")) \
            .field("power_consumption", float(payload.get("power_consumption")))
        
        # Xử lý timestamp từ payload nếu có
        ts = payload.get("timestamp")
        if ts:
            point.time(parser.parse(ts), WritePrecision.NS)
            
        write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
        # logger.debug(f"Saved data for {device_id} to InfluxDB")
    except Exception as e:
        logger.error(f"Error in MQTT on_message: {e}")

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

# --- Models & Schemas ---
class ControlCommand(BaseModel):
    device: str
    command: str
    room_id: Optional[str] = "room_A203"

# --- AI Logic ---
def load_ai_model():
    try:
        model = joblib.load(MODEL_PATH)
        features = joblib.load(FEATURE_NAMES_PATH)
        logger.info("AI Model loaded successfully")
        return model, features
    except Exception as e:
        logger.error(f"Failed to load AI model: {e}")
        return None, None

anomaly_model, feature_names = load_ai_model()

# --- Background Tasks ---

async def rule_engine_task():
    """Kiểm tra các quy tắc tự động mỗi 10 giây."""
    while True:
        try:
            # Lấy danh sách các phòng
            rooms_query = f'import "influxdata/influxdb/schema"\nschema.tagValues(bucket: "{INFLUXDB_BUCKET}", tag: "device_id")'
            rooms = query_api.query(org=INFLUXDB_ORG, query=rooms_query)
            
            for table in rooms:
                for record in table.records:
                    room_id = record.get_value()
                    
                    # Nếu đang có anomaly, bỏ qua điều khiển tự động
                    if is_room_anomaly.get(room_id, False):
                        continue
                        
                    # Lấy trạng thái mới nhất
                    latest_query = f'''
                    from(bucket: "{INFLUXDB_BUCKET}")
                        |> range(start: -1m)
                        |> filter(fn: (r) => r["_measurement"] == "telemetry")
                        |> filter(fn: (r) => r["device_id"] == "{room_id}")
                        |> last()
                        |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
                    '''
                    result = query_api.query(org=INFLUXDB_ORG, query=latest_query)
                    if not result: continue
                    
                    data = result[0].records[0].values
                    people = data.get("people_count", 0)
                    temp = data.get("temperature", 0)
                    light = data.get("light_intensity", 0)
                    ac = data.get("ac_state", "OFF")
                    l_state = data.get("light_state", "OFF")
                    
                    # 1. Tự động BẬT
                    if people > 0:
                        if temp > 28 and ac == "OFF":
                            mqtt_client.publish(TOPIC_CONTROL, json.dumps({"device": "ac", "command": "ON"}))
                            logger.info(f"Rule Engine: Auto-ON AC in {room_id} (Temp: {temp})")
                        if light < 200 and l_state == "OFF":
                            mqtt_client.publish(TOPIC_CONTROL, json.dumps({"device": "light", "command": "ON"}))
                            logger.info(f"Rule Engine: Auto-ON Light in {room_id} (Light: {light})")
                    
                    # 2. Tự động TẮT (Nếu vắng người trong 10 phút)
                    # (Để đơn giản, ở đây check people == 0 và đang bật, logic 10p có thể check range -10m)
                    if people == 0:
                        if ac == "ON" or l_state == "ON":
                            # Check 10 phút trước
                            check_query = f'''
                            from(bucket: "{INFLUXDB_BUCKET}")
                                |> range(start: -10m)
                                |> filter(fn: (r) => r["_measurement"] == "telemetry")
                                |> filter(fn: (r) => r["device_id"] == "{room_id}")
                                |> filter(fn: (r) => r["_field"] == "people_count")
                                |> mean()
                            '''
                            check_res = query_api.query(org=INFLUXDB_ORG, query=check_query)
                            if check_res and check_res[0].records[0].get_value() == 0:
                                if ac == "ON":
                                    mqtt_client.publish(TOPIC_CONTROL, json.dumps({"device": "ac", "command": "OFF"}))
                                if l_state == "ON":
                                    mqtt_client.publish(TOPIC_CONTROL, json.dumps({"device": "light", "command": "OFF"}))
                                logger.info(f"Rule Engine: Auto-OFF devices in {room_id} due to inactivity (10m)")

        except Exception as e:
            logger.error(f"Error in Rule Engine: {e}")
        await asyncio.sleep(10)

async def anomaly_detection_task():
    """Chạy dự báo Anomaly mỗi 5 phút."""
    while True:
        try:
            if not anomaly_model:
                await asyncio.sleep(60)
                continue
            
            room_id = "room_A203" # Tập trung vào phòng demo
            
            # Lấy 10 mẫu gần nhất
            query = f'''
            from(bucket: "{INFLUXDB_BUCKET}")
                |> range(start: -15m)
                |> filter(fn: (r) => r["_measurement"] == "telemetry")
                |> filter(fn: (r) => r["device_id"] == "{room_id}")
                |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
                |> limit(n: 10)
            '''
            tables = query_api.query(org=INFLUXDB_ORG, query=query)
            
            data_points = []
            for table in tables:
                for record in table.records:
                    data_points.append(record.values)
            
            if len(data_points) >= 10:
                # Tính toán features
                df = np.array([[
                    d.get("temperature", 25), d.get("humidity", 60), 
                    d.get("light_intensity", 300), d.get("power_consumption", 1)
                ] for d in data_points])
                
                features = []
                for i in range(4): # 4 variables
                    col_data = df[:, i]
                    features.extend([np.mean(col_data), np.std(col_data), np.min(col_data), np.max(col_data)])
                
                # Predict
                prediction = anomaly_model.predict([features])[0]
                is_anomaly = True if prediction == -1 else False
                
                is_room_anomaly[room_id] = is_anomaly
                
                if is_anomaly:
                    logger.warning(f"Anomaly Detected in {room_id}!")
                    anomaly_data = {
                        "is_anomaly": True,
                        "timestamp": datetime.now(timezone(timedelta(hours=7))).isoformat(),
                        "room_id": room_id,
                        "reason": "Extreme environmental values detected"
                    }
                    recent_anomalies.append(anomaly_data)
                    if len(recent_anomalies) > 50: recent_anomalies.pop(0)
                    
                    # Publish MQTT
                    mqtt_client.publish(TOPIC_ANOMALY, json.dumps(anomaly_data))
                    
                    # Write to InfluxDB
                    p = Point("anomalies").tag("device_id", room_id).field("is_anomaly", 1).field("reason", anomaly_data["reason"])
                    write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=p)

        except Exception as e:
            logger.error(f"Error in Anomaly Detection Task: {e}")
            
        await asyncio.sleep(300) # 5 minutes

# --- API Endpoints ---

@app.get("/api/rooms")
async def get_rooms():
    query = f'import "influxdata/influxdb/schema"\nschema.tagValues(bucket: "{INFLUXDB_BUCKET}", tag: "device_id")'
    result = query_api.query(org=INFLUXDB_ORG, query=query)
    rooms = []
    for table in result:
        for record in table.records:
            rooms.append(record.get_value())
    return rooms

@app.get("/api/rooms/{room_id}/latest")
async def get_latest(room_id: str):
    query = f'''
    from(bucket: "{INFLUXDB_BUCKET}")
        |> range(start: -1h)
        |> filter(fn: (r) => r["_measurement"] == "telemetry")
        |> filter(fn: (r) => r["device_id"] == "{room_id}")
        |> last()
        |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
    '''
    result = query_api.query(org=INFLUXDB_ORG, query=query)
    if not result:
        raise HTTPException(status_code=404, detail="No data found")
    return result[0].records[0].values

@app.get("/api/rooms/{room_id}/history")
async def get_history(room_id: str, minutes: int = 60):
    query = f'''
    from(bucket: "{INFLUXDB_BUCKET}")
        |> range(start: -{minutes}m)
        |> filter(fn: (r) => r["_measurement"] == "telemetry")
        |> filter(fn: (r) => r["device_id"] == "{room_id}")
        |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        |> sort(columns: ["_time"])
    '''
    result = query_api.query(org=INFLUXDB_ORG, query=query)
    history = []
    for table in result:
        for record in table.records:
            history.append(record.values)
    return history

@app.post("/api/control")
async def send_control(cmd: ControlCommand):
    payload = {"device": cmd.device, "command": cmd.command}
    mqtt_client.publish(TOPIC_CONTROL, json.dumps(payload))
    logger.info(f"Sent control command: {payload}")
    return {"status": "success", "sent": payload}

@app.get("/api/anomalies")
async def get_anomalies():
    return recent_anomalies

# --- Static Files & Dashboard ---
DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard")
if os.path.exists(DASHBOARD_DIR):
    # Mount at root so index.html can find style.css and app.js relatively.
    # Must be after all other routes.
    app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")

# --- Lifecycle ---
@app.on_event("startup")
async def startup_event():
    # Chạy MQTT loop trong thread riêng
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    threading.Thread(target=mqtt_client.loop_forever, daemon=True).start()
    
    # Khởi chạy background tasks
    asyncio.create_task(rule_engine_task())
    asyncio.create_task(anomaly_detection_task())
    logger.info("Background tasks started")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
