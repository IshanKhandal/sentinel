# Sentinel Demo vs. Live Operational Modes

> **Document Status:** ARCHITECTURE FREEZE (Phase 1)  
> **Protocol Standard:** Non-Hallucination & Evidence-First Engineering Rules ([docs/engineering-rules.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/engineering-rules.md), Rules 5, 6, 29, 30, 31)

---

## 1. The Two Operational States

The system formally supports **EXACTLY TWO** mutually isolated operational modes:

### `DEMO` MODE
- **Definition:** The platform operates using local synthetic fixtures, sample test videos, or mock API responses.
- **Purpose:** Development, automated continuous integration tests, and offline hackathon demonstration.
- **Labeling Standard:** Every UI component, camera feed, map marker, and report generated in DEMO mode MUST display a persistent, high-contrast badge: `[DEMO]`.
- **Constraint:** Demo data must NEVER be claimed or presented as real surveillance feeds or government records.

### `LIVE` MODE
- **Definition:** The platform processes exclusively genuine, verified surveillance streams, real hardware sensor packets, and authenticated government databases.
- **Rule on Missing Dependencies:** If a configured live integration (e.g., an RTSP camera stream or police database) becomes unreachable or is not yet configured:
  - The component **MUST NEVER** silently switch to `DEMO` mode or show simulated data.
  - The component **MUST** display:
    ```text
    UNAVAILABLE
    ```
    or
    ```text
    OFFLINE
    ```
  - It must **NEVER** display `LIVE` or `CONNECTED` unless live telemetry packets are actively flowing and verified.

---

## 2. UI Component Data-State Table

| Data State | When to Display | Visual Presentation |
|---|---|---|
| **`LIVE`** | Active, real-time data streaming from a verified authentic source. | Emerald Green badge with subtle pulse indicator |
| **`DEMO`** | Synthetic, mock, or prerecorded playback data in demo mode. | Amber Orange badge with bold `[DEMO]` label |
| **`OFFLINE`** | Live source configured, but connection dropped or timed out. | Dark Grey badge with slash icon |
| **`UNAVAILABLE`** | Resource not configured or required external service missing. | Crimson Red badge with warning indicator |
| **`UNKNOWN`** | Telemetry source provenance cannot be conclusively verified. | Muted Purple badge with question mark |

---

## 3. Code Isolation Architecture

- **Backend Flag:** `SENTINEL_OPERATION_MODE=DEMO` vs `SENTINEL_OPERATION_MODE=LIVE`.
- **Directory Isolation:** All mock datasets, video loops, and synthetic generator scripts reside strictly under `tests/fixtures/` and `src/mock/`.
- **Fail-Safe Guard:** Under `SENTINEL_OPERATION_MODE=LIVE`, all mock generator modules are completely bypassed and deactivated. An unconfigured live resource throws an explicit `IntegrationUnavailableException`.
