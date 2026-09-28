# Sentinel Scalability Architecture (~80,000 Camera Footprint)

> **Document Status:** ARCHITECTURE FREEZE (Phase 1)  
> **Protocol Standard:** Non-Hallucination & Evidence-First Engineering Rules ([docs/engineering-rules.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/engineering-rules.md))  
> **Rule 11 Enforcement:** Do NOT claim the current single-machine prototype can process 80,000 cameras. The prototype baseline is strictly local. This document defines the theoretical distributed architecture required to scale across Gujarat State.

---

## 1. Verified vs Theoretical Status Baseline

| Dimension | VERIFIED PROTOTYPE REALITY | THEORETICAL 80,000-CAMERA ARCHITECTURE |
|---|---|---|
| **Node Deployment** | Single machine (Windows developer workstation) | Distributed multi-region Kubernetes clusters |
| **Simultaneous Feeds** | 1 to 4 test streams (MP4/RTSP local loop) | 80,000 concurrent IP cameras |
| **Ingestion Workers** | Local Python threads/asyncio processes | 800+ containerized Regional Stream Gateways |
| **Inference Hardware** | Local CPU (Intel/AMD) / Single local GPU | Distributed GPU clusters (NVIDIA A10 / L4 / T4) |
| **Event Broker** | In-memory `asyncio.Queue` / Local SQLite | Apache Kafka / Distributed Redis Cluster |
| **Data Store** | Single SQLite file / Local PostgreSQL | Sharded PostgreSQL + TimescaleDB + S3 Storage |
| **Aggregate Bandwidth**| < 10 Mbps local loop | ~160 Gbps aggregate state-wide ingress |

---

## 2. Distributed Scale-Out Topology

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        GUJARAT STATE CCTV FOOTPRINT                     │
│                             (~80,000 Cameras)                          │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
    ┌───────────────────────────────┼───────────────────────────────┐
    ▼                               ▼                               ▼
[Region 1: Ahmedabad]      [Region 2: Surat]              [Region 3: Vadodara...]
 (20,000 Cameras)           (15,000 Cameras)               (10,000 Cameras)
    │                               │                               │
    ▼                               ▼                               ▼
[Regional Stream Gateways] [Regional Stream Gateways]     [Regional Stream Gateways]
    │                               │                               │
    ▼                               ▼                               ▼
[Edge Inference Pods]      [Edge Inference Pods]          [Edge Inference Pods]
    │                               │                               │
    └───────────────────────────────┼───────────────────────────────┘
                                    │ (Detection Metadata & Alert Events Only)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   STATE CENTRAL COMMAND & CONTROL                      │
│                                                                        │
│   ├── Apache Kafka Message Bus (High-throughput Event Ingestion)       │
│   ├── Central Sharded PostgreSQL / TimescaleDB (Historical Storage)   │
│   ├── Distributed Watchlist In-Memory Cache (Sub-millisecond matching) │
│   ├── Central API Gateway & WebSocket Clusters (Operator Web UIs)      │
│   └── MinIO / S3 Object Storage (Cropped Plate Evidence Snapshots)     │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Scale-Out Engineering Specifications

### 3.1 Regional Stream Gateways & Ingestion Workers
- **Ingress Bandwidth Calculation:**
  - 80,000 cameras @ 2 Mbps (H.264 1080p stream) = **160 Gbps** total bandwidth.
  - Streaming 160 Gbps over WAN to a single central datacenter is impractical and vulnerable to network bottlenecks.
  - **Solution:** 33 District Police Command Centers (DCCs). Feeds terminate locally at Regional Stream Gateways.
- **Worker Density:** Each gateway server (e.g., 64-core AMD EPYC, 128 GB RAM) handles ~100 RTSP demuxing streams. 80,000 cameras require **800 gateway instances**.

### 3.2 Edge Inference & GPU Allocation
- **Target Frame Rate for Detection:** Decimate incoming 25/30 FPS video to **5 to 8 FPS** per camera for AI inference. This reduces compute demand by 75% without compromising vehicle detection accuracy.
- **Inference Throughput per GPU:**
  - Modern enterprise GPU (e.g., NVIDIA L4 with TensorRT FP16): ~300 FPS batch inference throughput.
  - At 6 FPS per camera, 1 GPU can process: $300 / 6 = 50$ cameras simultaneously.
  - 80,000 cameras require **~1,600 GPUs** across the state grid.

### 3.3 Message Queue & Central Event Ingestion
- **Event Traffic Volume:**
  - Assuming an average busy intersection yields 1 vehicle detection every 3 seconds per camera:
  - $80,000 \times 0.33 \approx 26,400\text{ detections/second}$ across the state.
  - Apache Kafka cluster (3 brokers, replication factor 3) handles > 100,000 msgs/sec easily.

### 3.4 Database Sharding & Storage Scaling
- **Daily Ingestion Storage:**
  - 26,400 detections/sec = ~2.28 billion detections/day.
  - Relational metadata: 200 bytes per detection = **~450 GB/day**.
  - **Storage Architecture:** TimescaleDB / Citus PostgreSQL partitioned by date and district ID. Older data (> 90 days) compressed into columnar Parquet files on object storage (MinIO / S3).

### 3.5 High Availability, Failover & Disaster Recovery
- **Stream Gateway Failover:** Heartbeat supervisor restarts failed RTSP worker pods in < 5 seconds.
- **Database High Availability:** Active-Passive PostgreSQL clustering with Patroni and automated Raft leader election.
- **Disaster Recovery (DR):** Asynchronous transaction log shipping to a secondary warm-standby datacenter in Gandhinagar.
