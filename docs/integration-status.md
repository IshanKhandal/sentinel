# External Integration Register

> **Protocol Note:** In accordance with Project Rule 28 and Phase 0/1/2/3 Directives, every external integration must be tracked below. Under no circumstances should endpoints, hosts, credentials, or schemas be fabricated.

| Integration | Purpose | Expected Source | Verified? | Endpoint / Resource | Authentication | Current Status | Evidence | Blocker |
|---|---|---|---|---|---|---|---|---|
| Git Remote Repository | Source control and collaboration | GitHub (`IshanKhandal/sentinel`) | YES | `https://github.com/IshanKhandal/sentinel.git` | Git Credential Manager / SSH | CONNECTED | Verified via `git remote -v`, `git push -u origin main` (code 0) | None |
| SQLite (Local Engine) | Development persistence for all 19 system tables | Local Python standard library `sqlite3` | YES | `sqlite:///./sentinel.db` | Local filesystem file permissions | VERIFIED WORKING | 19 tables created, migrations tested, 22 pytest tests passing | None |
| Alembic Migration Engine | Schema evolution, automated migrations, and drift checks | Python `alembic` package | YES | `alembic.ini` / `alembic/` | Local CLI access | VERIFIED WORKING | Clean initial migration, upgrade/downgrade/upgrade verified, zero schema drift | None |
| Official Sentinel Catalogue Specification | Authoritative schema contract for camera IDs, locations, codecs, URLs | Official Sentinel Technical Resource | YES | `GET http://<host>/api/ingest` | Unauthenticated / None specified in contract | VERIFIED SPECIFICATION | Verified from official specification in user prompt | Real host address unconfigured |
| Sentinel Catalogue Endpoint | Live camera discovery & metadata ingestion | Official Sentinel CCTV Gateway | NO | `http://<host>/api/ingest` | UNKNOWN | BLOCKED | Workspace and env search yielded zero stream hosts; SENTINEL_STREAM_HOST is unset | Actual host address is UNKNOWN / BLOCKED |
| Catalogue Connection | Live network polling of `/api/ingest` | Official Sentinel CCTV Gateway | NO | `GET /api/ingest` | UNKNOWN | BLOCKED | `SentinelCatalogueClient.fetch_catalogue()` raises `CatalogueHostNotConfiguredError` | Host unconfigured; no fake host substituted |
| Official RTSP Stream Protocol | High-performance video feed for AI inference & decoding | Sentinel RTSP Server | YES | `rtsp://<host>:8554/stream/<id>` | Unauthenticated / None specified | VERIFIED SPECIFICATION | Protocol pattern verified from official contract; forced TCP invariant enforced | Real host unconfigured |
| Official WebRTC / WHEP Protocol | Low-latency browser surveillance preview | Sentinel WHEP Gateway | YES | `http://<host>:8889/stream/<id>/whep` | Unauthenticated / None specified | VERIFIED SPECIFICATION | Protocol pattern verified from official contract | Real host unconfigured |
| Official HLS Stream Protocol | Video streaming for dashboards & restricted networks | Sentinel HLS Server | YES | `http://<host>/live/stream/<id>/index.m3u8` | Unauthenticated / None specified | VERIFIED SPECIFICATION | Protocol pattern verified from official contract | Real host unconfigured |
| Actual Live Stream Connection | Network packet decoding and frame display | Target surveillance camera hardware | NO | `rtsp://<host>:8554/...` | UNKNOWN | BLOCKED | Zero live streams accessible; host is unconfigured | Stream host is UNKNOWN / BLOCKED |
| PostgreSQL (Production Target) | Enterprise relational and geospatial persistence | Remote / Containerized PostgreSQL 16 server | NO | `postgresql+psycopg2://...` | Database user/password credentials | IMPLEMENTED + UNTESTED | Schema written using cross-dialect types; PostgreSQL server not installed/running locally | PostgreSQL CLI not installed, Docker daemon stopped |
| Police Watchlist / Vahan API | Vehicle registration and stolen/wanted vehicle lookup | Government transport / police database | NO | UNKNOWN (DO NOT INVENT) | UNKNOWN | UNVERIFIED | No API endpoints or schemas present in workspace | No API endpoints or access credentials provided |
| Map / GIS Tile Service | Rendering geospatial camera locations and vehicle routes | Leaflet.js with public OpenStreetMap tile fallback | YES | `https://tile.openstreetmap.org/{z}/{x}/{y}.png` | None / Public tile access | VERIFIED WORKING (FALLBACK) | Functional in `frontend/gis_preview.html`; tile load errors explicitly tracked as `MAP TILES UNAVAILABLE` | Commercial tile API key unconfigured (development fallback active) |
| GIS Spatial Engine | WGS 84 calculations, GeoJSON RFC 7946 generation, Haversine nearby queries | Pure Python in-memory GIS Service | YES | Internal Service (`backend/app/services/gis_service.py`) | Application context | VERIFIED WORKING | 15 unit/API tests passing; zero coordinate hallucination enforced | None |
| Sentinel Camera Coordinates | Verified real-world GPS coordinates for catalogue cameras | Official `/api/ingest` payload | NO | `http://<host>/api/ingest` | UNKNOWN | UNKNOWN / ZERO RECORDED | Catalogue host unconfigured; zero coordinates in database; all cameras unmapped | Sentinel stream host is unconfigured |
| Model Weights Storage | Pre-trained weights for vehicle detection & ANPR | Ultralytics / Hugging Face / Custom storage | NO | UNKNOWN | UNKNOWN | UNVERIFIED | No weights or model files present in workspace | Model selection pending challenge specifications |

---

## Status Definitions
- **VERIFIED SPECIFICATION:** Official technical contract and protocol standards confirmed from official project resources.
- **CONNECTED / VERIFIED WORKING:** Verified live connection, successful round-trip execution, and automated test passage.
- **IMPLEMENTED + UNTESTED:** Schema/adapter implemented to specification but underlying server environment is not present locally to test.
- **UNVERIFIED:** Resource exists conceptually or in specifications but has not been tested.
- **BLOCKED:** Cannot proceed due to missing endpoints, credentials, or network barriers (e.g., host unknown).
