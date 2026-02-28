from flask import Flask, render_template, request, jsonify
import os
import sys
import time
import threading
import queue
from collections import deque
import pandas as pd

from sklearn.decomposition import PCA

# Ensure project root is on sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from csv_stream.config import FEATURES, WINDOW_SIZE, ALERT_THRESHOLD
from csv_stream.loader import stream_csv
from csv_stream.aggregator import temporal_aggregate
from csv_stream.detector import AnomalyDetector

app = Flask(__name__)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

MODEL_PATH = "../Dos_Model/model/iso_forest_windowed_model.joblib"

# Worker behavior
WORKER_SLEEP_SEC = 0.02        # scan pace
MAX_LINES_PER_BATCH = 50       # worker batches lines before pushing to queue
MAX_CLUSTER_POINTS = 300       # rolling history for plot
QUEUE_MAX = 5000               # safety cap

# PCA settings
PCA_FIT_MIN_WINDOWS = 80       # wait until we have enough windows before fitting PCA
PCA_REFIT_EVERY = 0            # set >0 to refit periodically (e.g., 500) if you want; 0 = fit once

# ---- Model ----
try:
    detector = AnomalyDetector(MODEL_PATH)
except Exception as e:
    print(f"Model Load Error: {e}")
    detector = None

# ---- Shared state guarded by locks ----
state_lock = threading.Lock()
stream_state = {
    "initialized": False,
    "running": False,
    "rows_consumed": 0,
    "last_score": None,
    "worst_score_seen": None,
    "window_size": WINDOW_SIZE,
    "alert_threshold": ALERT_THRESHOLD,
    "cluster_axes": {"x": "PC1", "y": "PC2"},
    "cluster_points": [],  # capped history: {"x","y","is_anomaly"}
    "complete": False,
    "error": None,
}

# Worker control
worker_thread = None
stop_event = threading.Event()

# Queue of outbound updates for /stream to drain
out_q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)


def _q_put(item: dict) -> None:
    """Put to queue; if full, drop some old messages to make room."""
    try:
        out_q.put_nowait(item)
    except queue.Full:
        try:
            for _ in range(100):
                out_q.get_nowait()
        except queue.Empty:
            pass
        try:
            out_q.put_nowait(item)
        except queue.Full:
            pass


def worker_scan(csv_path: str) -> None:
    global detector

    buffer = deque(maxlen=WINDOW_SIZE)
    iterator = stream_csv(csv_path)

    # PCA state local to worker thread
    pca = PCA(n_components=2)
    pca_fitted = False
    # Collect window feature rows for PCA fitting (each is a 1D vector)
    pca_fit_rows = []
    windows_scored = 0

    with state_lock:
        stream_state["running"] = True
        stream_state["complete"] = False
        stream_state["error"] = None

    lines_batch = []
    new_cluster_batch = []

    try:
        while not stop_event.is_set():
            try:
                row = next(iterator)
            except StopIteration:
                with state_lock:
                    stream_state["running"] = False
                    stream_state["complete"] = True
                if lines_batch or new_cluster_batch:
                    _q_put({"status": "tick", "lines": lines_batch})
                _q_put({"status": "complete"})
                return

            buffer.append(row)

            with state_lock:
                stream_state["rows_consumed"] += 1
                rows = stream_state["rows_consumed"]

            # warming up (need 50 rows in buffer)
            if len(buffer) < WINDOW_SIZE:
                if rows % 25 == 0:
                    _q_put({"status": "warming_up"})
                time.sleep(WORKER_SLEEP_SEC)
                continue

            buffer_df = pd.concat(list(buffer), ignore_index=True)
            X_temporal = temporal_aggregate(buffer_df, FEATURES)
            if X_temporal.empty:
                time.sleep(WORKER_SLEEP_SEC)
                continue

            score = float(detector.score(X_temporal)[-1])
            is_anomaly = int(score < ALERT_THRESHOLD)
            windows_scored += 1

            # Update stats
            with state_lock:
                stream_state["last_score"] = score
                if stream_state["worst_score_seen"] is None or score < stream_state["worst_score_seen"]:
                    stream_state["worst_score_seen"] = score

            # ---- PCA cluster point ----
            # Use the latest aggregated window row
            x_row = X_temporal.iloc[-1].values.astype("float64")
            pca_fit_rows.append(x_row)

            # Fit PCA once we have enough windows
            if (not pca_fitted) and (len(pca_fit_rows) >= PCA_FIT_MIN_WINDOWS):
                pca.fit(pd.DataFrame(pca_fit_rows).values)
                pca_fitted = True

            # Optional periodic refit (usually not necessary)
            if PCA_REFIT_EVERY and pca_fitted and (windows_scored % PCA_REFIT_EVERY == 0):
                pca.fit(pd.DataFrame(pca_fit_rows[-max(PCA_FIT_MIN_WINDOWS, 200):]).values)

            if pca_fitted:
                xy = pca.transform([x_row])[0]
                x_val = float(xy[0])
                y_val = float(xy[1])
            else:
                # Fallback until PCA is fitted (use first 2 dims)
                x_val = float(x_row[0])
                y_val = float(x_row[1]) if len(x_row) > 1 else 0.0

            pt = {"x": x_val, "y": y_val, "is_anomaly": is_anomaly}
            new_cluster_batch.append(pt)

            with state_lock:
                stream_state["cluster_points"].append(pt)
                if len(stream_state["cluster_points"]) > MAX_CLUSTER_POINTS:
                    stream_state["cluster_points"] = stream_state["cluster_points"][-MAX_CLUSTER_POINTS:]

            # ---- Log line (no timestamps) ----
            if is_anomaly:
                latest = buffer_df.iloc[-1]
                fps = float(latest.get("flow_packets_s", 0.0))
                syns = float(latest.get("syn_flag_count", 0.0))
                msg = (
                    f"[ALERT] Threshold={ALERT_THRESHOLD:.5f} | "
                    f"Score={score:.5f} | "
                    f"Packets/s={fps:.1f} | "
                    f"SYNs={syns:.0f}"
                )
                lines_batch.append({"type": "alert", "message": msg, "score": score})
            else:
                msg = f"[OK] Threshold={ALERT_THRESHOLD:.5f} | Score={score:.5f}"
                lines_batch.append({"type": "ok", "message": msg, "score": score})

            # Flush periodically
            if len(lines_batch) >= MAX_LINES_PER_BATCH:
                _q_put({"status": "tick", "lines": lines_batch})
                lines_batch = []

            time.sleep(WORKER_SLEEP_SEC)

    except Exception as e:
        with state_lock:
            stream_state["running"] = False
            stream_state["error"] = str(e)
        _q_put({"status": "error", "error": str(e)})


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    global worker_thread

    if detector is None:
        return jsonify(error="Model not loaded"), 500

    if "file" not in request.files:
        return jsonify(error="No file uploaded"), 400

    f = request.files["file"]
    if not f or f.filename == "":
        return jsonify(error="No selected file"), 400

    save_path = os.path.join(UPLOAD_DIR, "uploaded_stream.csv")
    f.save(save_path)

    # Stop existing worker
    stop_event.set()
    if worker_thread and worker_thread.is_alive():
        worker_thread.join(timeout=2.0)

    # Reset worker + queue
    stop_event.clear()
    while True:
        try:
            out_q.get_nowait()
        except queue.Empty:
            break

    with state_lock:
        stream_state["initialized"] = True
        stream_state["running"] = False
        stream_state["rows_consumed"] = 0
        stream_state["last_score"] = None
        stream_state["worst_score_seen"] = None
        stream_state["cluster_points"] = []
        stream_state["cluster_axes"] = {"x": "PC1", "y": "PC2"}
        stream_state["complete"] = False
        stream_state["error"] = None

    worker_thread = threading.Thread(target=worker_scan, args=(save_path,), daemon=True)
    worker_thread.start()

    return jsonify(
        status="stream_initialized",
        window_size=WINDOW_SIZE,
        alert_threshold=ALERT_THRESHOLD,
        cluster_axes={"x": "PC1", "y": "PC2"},
    )


@app.route("/stream")
def stream():
    # Drain some queue messages
    drained = []
    for _ in range(200):
        try:
            drained.append(out_q.get_nowait())
        except queue.Empty:
            break

    with state_lock:
        snapshot = {
            "rows_consumed": stream_state["rows_consumed"],
            "last_score": stream_state["last_score"],
            "worst_score_seen": stream_state["worst_score_seen"],
            "cluster_points": stream_state["cluster_points"],
            "cluster_axes": stream_state["cluster_axes"],
            "running": stream_state["running"],
            "complete": stream_state["complete"],
            "error": stream_state["error"],
        }

    lines = []
    status = None
    for item in drained:
        if item.get("status") == "tick" and item.get("lines"):
            lines.extend(item["lines"])
            status = "tick"
        elif item.get("status") == "warming_up":
            status = status or "warming_up"
        elif item.get("status") == "complete":
            status = "complete"
        elif item.get("status") == "error":
            status = "error"

    if snapshot["error"]:
        return jsonify(status="error", error=snapshot["error"], **snapshot)

    if status == "complete" or snapshot["complete"]:
        return jsonify(status="complete", **snapshot)

    if status == "warming_up" and snapshot["rows_consumed"] < WINDOW_SIZE:
        return jsonify(status="warming_up", needed=WINDOW_SIZE, **snapshot)

    if lines:
        return jsonify(status="tick", lines=lines, **snapshot)

    return jsonify(status="ok", **snapshot)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)