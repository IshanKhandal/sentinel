# Demo Mode & Simulation Boundary Specification

> **Protocol Note:** In accordance with Project Rules 5, 6, 29, and 30:
> - Never silently replace a missing real dependency with fake data.
> - Clearly label and isolate demo/mock data from live/production logic.
> - Trustworthy UI data-states must be maintained at all times.

## System Reality Matrix

| Subsystem / Component | Current State | Real Components | Simulated / Mock Components | Data Provenance | UI Indicator Flag |
|---|---|---|---|---|---|
| Project Architecture & Documentation | REAL | Markdown specifications, Git structure | None | Developer & User specified | N/A |
| Camera Feeds | NONE | None | None | None | `OFFLINE` / `UNAVAILABLE` |
| Video Analytics / Inference | NONE | None | None | None | `OFFLINE` / `UNAVAILABLE` |
| Watchlist / Person / Vehicle Data | NONE | None | None | None | `UNAVAILABLE` |
| GIS / Map Coordinates | NONE | None | None | None | `UNAVAILABLE` |

---

## Allowed UI Data States (Rule 30)

Every visual component or widget presenting data must display one of the following states:

1. **`LIVE`**: Active, real-time data received from an authentic, verified source (e.g., active hardware sensor or live streaming server). NEVER display unless live connection is verified and packets are being received.
2. **`DEMO`**: Clearly flagged synthetic, mock, or prerecorded playback data used for demonstration. Must be visibly badged with a high-contrast `[DEMO]` indicator.
3. **`OFFLINE`**: Intended real endpoint or stream exists in configuration but is currently unreachable.
4. **`UNKNOWN`**: Data origin or feed state cannot be determined with certainty.
5. **`UNAVAILABLE`**: No data source, feed, or simulation is configured.

---

## Isolation Rules
- Mock/Demo data generators must reside in dedicated directories (e.g., `mock/`, `fixtures/`, or behind an explicit `DEMO_MODE=true` environment flag).
- In production or default mode, attempting to access an unconfigured live resource must result in an explicit `UNAVAILABLE` or error status rather than silently falling back to mock data.
