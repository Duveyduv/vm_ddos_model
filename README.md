# DDoS Anomaly Detection Dashboard

## Overview

This project implements a real-time DDoS anomaly detection system using
an Isolation Forest model applied to temporally aggregated network flow
data. The system analyzes traffic in rolling windows, performs
statistical feature aggregation, and visualizes anomalies through a live
web-based dashboard.

The application consists of:

-   A feature engineering and model inference pipeline
-   A multithreaded streaming engine
-   A Flask-based dashboard interface
-   PCA-based visualization of high-dimensional traffic behavior

The objective is to detect coordinated anomalous behavior across
correlated network features rather than relying on single-metric
thresholding.

------------------------------------------------------------------------

## Detection Methodology

### Window-Based Analysis

Traffic is processed in rolling windows of 50 flows. Instead of scoring
individual rows independently, each window is aggregated into
statistical features:

-   Mean
-   Standard deviation
-   Minimum
-   Maximum

This transforms raw flow data into a behavioral representation of
network activity over time.

An anomaly flag indicates that the window as a whole deviates from
learned normal patterns. It does not imply that every individual flow
inside that window is malicious.

This approach enables detection of coordinated DDoS characteristics such
as:

-   Elevated packet rates
-   Abnormal SYN flag concentrations
-   Timing irregularities
-   Correlated byte distribution shifts

------------------------------------------------------------------------

### Isolation Forest

The model uses an Isolation Forest trained on benign traffic windows.

Key properties:

-   Unsupervised anomaly detection
-   Operates in high-dimensional feature space
-   Produces a decision score per window
-   Lower score indicates more anomalous behavior

A calibrated threshold derived from validation quantiles determines
anomaly classification.

------------------------------------------------------------------------

### PCA Visualization

The dashboard visualizes traffic windows using the first two principal
components (PC1 and PC2).

Principal Component Analysis reduces the high-dimensional feature space
into a 2D projection that preserves maximum variance structure.

This visualization:

-   Does not influence model predictions
-   Provides interpretability of traffic distribution
-   Highlights displacement of anomalous windows from normal clusters

------------------------------------------------------------------------

## Architecture

### Backend

-   Python
-   Flask
-   Scikit-learn
-   Multithreaded streaming worker
-   Thread-safe queue for UI updates

The worker thread:

1.  Streams CSV flow data
2.  Maintains a rolling buffer of 50 flows
3.  Aggregates window statistics
4.  Computes anomaly score
5.  Updates log output, PCA projection, score metrics, and anomaly
    counters

------------------------------------------------------------------------

### Frontend

-   Tailwind CSS
-   Chart.js scatter visualization
-   Polling-based live updates
-   Smart autoscroll for alert log
-   Dynamic anomaly counter
-   Worst score tracking

The UI displays:

-   Total anomalies detected
-   Alert threshold
-   Last anomaly score
-   Worst score observed
-   Real-time log output
-   PCA cluster visualization

------------------------------------------------------------------------

## Project Structure

Csv_stream/ 
* aggregator.py 
* config.py 
* detector.py 
* loader.py

gui/ 
* app.py
* templates/
    * index.html

------------------------------------------------------------------------

## Execution Flow

1.  Upload network flow CSV.
2.  Worker thread begins streaming analysis.
3.  Each 50-row window is aggregated and scored.
4.  Anomaly decision is made.
5.  Results are pushed to the UI queue.
6.  Dashboard updates continuously.

------------------------------------------------------------------------

## Key Design Decisions

-   Window-based behavioral detection instead of per-flow scoring
-   Quantile-based threshold calibration
-   PCA for visualization rather than raw feature plotting
-   Multithreaded architecture to decouple detection from UI polling
-   Rolling cluster history capped for performance stability

------------------------------------------------------------------------

## Limitations

-   PCA visualization is a projection and does not represent full
    separability.
-   Designed for offline CSV ingestion; not yet integrated with live
    packet capture.
-   In-memory state; scaling to multi-worker production requires
    external state management such as Redis.

------------------------------------------------------------------------

## Intended Use

This system is designed for:

-   Security analytics research
-   Behavioral anomaly detection demonstrations
-   SOC workflow visualization
-   Academic or portfolio demonstration of applied machine learning in
    cybersecurity
