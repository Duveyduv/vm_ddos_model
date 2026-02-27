from flask import Flask, render_template, request, jsonify
import pandas as pd
from collections import deque
import io
import time

# Importing your uploaded logic
from csv_stream.config import FEATURES, WINDOW_SIZE, ALERT_THRESHOLD
from csv_stream.loader import clean_cols
from csv_stream.aggregator import temporal_aggregate
from csv_stream.detector import AnomalyDetector

app = Flask(__name__)

scan_start_time = time.time()

# Initialize your detector (ensure the path to your .joblib is correct)
try:
    detector = AnomalyDetector("model/iso_forest_windowed_model.joblib")
except Exception as e:
    print(f"Model Load Error: {e}")
    detector = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    try:
        # Load the uploaded CSV
        df = pd.read_csv(io.StringIO(file.stream.read().decode("UTF8")))
        df = clean_cols(df)
        
        # We need at least WINDOW_SIZE rows to run your specific model logic
        if len(df) < WINDOW_SIZE:
            return jsonify({'error': f'File too small. Need at least {WINDOW_SIZE} rows.'}), 400

        # Process the last window for a "Snapshot" scan
        buffer_df = df.tail(WINDOW_SIZE)
        X_temporal = temporal_aggregate(buffer_df, FEATURES)
        
        if X_temporal.empty:
            return jsonify({'error': 'Aggregation failed.'}), 400

        score = float(detector.score(X_temporal)[-1])
        is_anomaly = score < ALERT_THRESHOLD

        return jsonify({
            "status": "DDoS Anomaly Detected" if is_anomaly else "Traffic Normal",
            "score": f"{score:.4f}",
            "threat_level": "High" if is_anomaly else "Low",
            "recommendation": "Initiate Rate Limiting" if is_anomaly else "System stable."
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/uptime')
def uptime():
    elapsed = int(time.time() - scan_start_time)

    hours = elapsed // 3600
    minutes = (elapsed % 3600) // 60
    seconds = elapsed % 60

    return jsonify({
        "uptime": f"{hours:02}:{minutes:02}:{seconds:02}"
    })

if __name__ == '__main__':
    app.run(debug=True)