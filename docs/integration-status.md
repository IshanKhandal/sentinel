# External Integration Register

> **Protocol Note:** In accordance with Project Rule 28 and Phase 0 Audit Directive 12, every external integration must be tracked below. Under no circumstances should endpoints, hosts, credentials, or schemas be fabricated.

| Integration | Purpose | Expected Source | Verified? | Endpoint / Resource | Authentication | Current Status | Evidence | Blocker |
|---|---|---|---|---|---|---|---|---|
| Git Remote Repository | Source control and collaboration | GitHub (`IshanKhandal/sentinel`) | YES | `https://github.com/IshanKhandal/sentinel.git` | Git Credential Manager / SSH | CONNECTED | Verified via `git remote -v`, `git push -u origin main` (code 0) | None |
| Sentinel CCTV Streams | Ingestion of live or recorded surveillance video | Gujarat Police CCTV network / Hackathon test server | NO | UNKNOWN (DO NOT INVENT) | UNKNOWN | UNVERIFIED | Workspace search returned no stream URLs or credentials | No RTSP/HLS stream addresses or camera credentials provided |
| Police Watchlist / Vahan API | Vehicle registration and stolen/wanted vehicle lookup | Government transport / police database | NO | UNKNOWN (DO NOT INVENT) | UNKNOWN | UNVERIFIED | No API endpoints or schemas present in workspace | No API endpoints or access credentials provided |
| Map / GIS Tile Service | Rendering geospatial camera locations and vehicle routes | OpenStreetMap / Mapbox / Google Maps | NO | UNKNOWN | UNKNOWN | UNVERIFIED | No map tokens or tile endpoints configured | Awaiting provider decision and API keys |
| Model Weights Storage | Pre-trained weights for vehicle detection & ANPR | Ultralytics / Hugging Face / Custom storage | NO | UNKNOWN | UNKNOWN | UNVERIFIED | No weights or model files present in workspace | Model selection pending challenge specifications |
| Database Engine | Persistence of detections, cameras, and alert logs | PostgreSQL / SQLite / Redis | NO | UNKNOWN | UNKNOWN | UNVERIFIED | No active database connection or configuration | Docker daemon stopped; no local PostgreSQL server running |

---

## Status Definitions
- **CONNECTED:** Verified live connection and successful round-trip communication.
- **UNVERIFIED:** Resource exists conceptually or in specifications but has not been tested.
- **MOCKED:** Synthetic adapter in place with explicit isolation boundaries.
- **BLOCKED:** Cannot proceed due to missing endpoints, credentials, or network barriers.
