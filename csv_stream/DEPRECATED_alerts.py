from datetime import datetime

def console_alert(df):
    anomalies = df[df["is_anomaly"] == 1]

    for _, row in anomalies.iterrows():
        print(
            f"[ALERT] {datetime.now().isoformat()} | "
            f"Score={row['anomaly_score']:.5f} | "
            f"Packets/s={row['flow_packets_s']:.1f} | "
            f"SYNs={row['syn_flag_count']}"
        )