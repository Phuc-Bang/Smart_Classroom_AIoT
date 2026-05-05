import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
import joblib
import os

# Cấu hình
NUM_SAMPLES = 5000
WINDOW_SIZE = 10
CONTAMINATION = 0.05
MODEL_PATH = "model.pkl"

def generate_synthetic_data(num_windows, window_size):
    """Sinh dữ liệu giả lập cho việc huấn luyện."""
    data_list = []
    
    for _ in range(num_windows):
        # Xác định xem window này có phải là anomaly không (5% xác suất)
        is_anomaly = np.random.rand() < CONTAMINATION
        
        if is_anomaly:
            # Dữ liệu bất thường: cực đoan
            temp = np.random.uniform(35, 50, window_size)
            hum = np.random.uniform(10, 30, window_size)
            light = np.random.uniform(800, 1500, window_size)
            power = np.random.uniform(5, 10, window_size)
        else:
            # Dữ liệu bình thường
            temp = np.random.normal(28, 2, window_size)
            hum = np.random.normal(60, 5, window_size)
            light = np.random.normal(400, 50, window_size)
            power = np.random.normal(2, 0.5, window_size)
            
        # Tính toán 16 features
        features = [
            np.mean(temp), np.std(temp), np.min(temp), np.max(temp),
            np.mean(hum), np.std(hum), np.min(hum), np.max(hum),
            np.mean(light), np.std(light), np.min(light), np.max(light),
            np.mean(power), np.std(power), np.min(power), np.max(power)
        ]
        data_list.append(features)
        
    cols = []
    for var in ['temp', 'hum', 'light', 'power']:
        for stat in ['mean', 'std', 'min', 'max']:
            cols.append(f"{var}_{stat}")
            
    return pd.DataFrame(data_list, columns=cols)

def train_model():
    print(f"--- Đang sinh dữ liệu giả lập ({NUM_SAMPLES} mẫu)... ---")
    df = generate_synthetic_data(NUM_SAMPLES, WINDOW_SIZE)
    
    print("--- Đang huấn luyện mô hình Isolation Forest... ---")
    # Isolation Forest rất hiệu quả cho phát hiện bất thường không cần nhãn (unsupervised)
    model = IsolationForest(
        contamination=CONTAMINATION,
        random_state=42,
        n_estimators=100
    )
    
    # Huấn luyện
    model.fit(df)
    
    # Kiểm tra thử kết quả trên chính tập huấn luyện
    preds = model.predict(df)
    anomalies_found = (preds == -1).sum()
    
    print(f"Kết quả huấn luyện:")
    print(f"- Tổng số mẫu: {len(df)}")
    print(f"- Số lượng bất thường phát hiện: {anomalies_found} ({anomalies_found/len(df)*100:.2f}%)")
    
    # Lưu model
    joblib.dump(model, MODEL_PATH)
    print(f"--- Đã lưu mô hình thành công tại: {os.path.abspath(MODEL_PATH)} ---")
    
    # Lưu danh sách feature để dùng cho inference sau này
    feature_names = df.columns.tolist()
    joblib.dump(feature_names, "feature_names.pkl")
    print("--- Đã lưu danh sách feature tại: feature_names.pkl ---")

if __name__ == "__main__":
    train_model()
