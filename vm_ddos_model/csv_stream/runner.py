import pandas as pd
from collections import deque

from config import FEATURES, WINDOW_SIZE, ALERT_THRESHOLD
from loader import stream_csv
from aggregator import temporal_aggregate
from detector import AnomalyDetector


def main():
    detector = AnomalyDetector("vm_ddos_model/model/iso_forest_windowed_model.joblib")

    buffer = deque(maxlen=WINDOW_SIZE)
    buffer_df = pd.DataFrame()

    for row in stream_csv("vm_ddos_model/Monday-WorkingHours.pcap_ISCX.csv"):
        buffer.append(row)

        if len(buffer) < WINDOW_SIZE:
            continue

        buffer_df = pd.concat(list(buffer), ignore_index=True)

        X_temporal = temporal_aggregate(buffer_df, FEATURES)

        if X_temporal.empty:
            continue

        score = detector.score(X_temporal)[-1]

        if score < ALERT_THRESHOLD:
            print(
                f"[ALERT] DDoS anomaly detected | "
                f"score={score:.4f}"
            )
        else:
            print(f"[OK] score={score:.4f}")


if __name__ == "__main__":
    main()
