# Project Assumptions Register

> **Protocol Note:** In accordance with Project Rule 27 and Phase 0/1/2/3 Directives, every assumption must be explicitly logged. Unrecorded assumptions are strictly forbidden. In all cases, `UNKNOWN` is preferred over `ASSUMED` unless strictly necessary for an environmental baseline.

## Active Assumptions Register

| ID | Date Recorded | Category | Stated Assumption | Empirical Basis / Justification | Risk Level | Status |
|---|---|---|---|---|---|---|
| ASM-001 | 2026-09-28 | Operating Environment | Host machine is 64-bit Windows with PowerShell shell, Node.js (`v24.16.0`), Python (`3.14.3`), and Docker CLI (`29.5.3`) available. | Confirmed via direct terminal inspection (`node -v`, `python --version`, `docker --version`). | Low | VERIFIED |
| ASM-002 | 2026-09-28 | Media Processing Tools | `ffmpeg` is not currently in system PATH and must either be installed locally or run via a containerized service. | Confirmed via `ffmpeg -version` failure (`CommandNotFoundException`). | Medium | VERIFIED |
| ASM-003 | 2026-09-28 | Database Availability | PostgreSQL and Redis CLI tools are not installed in system PATH; containerized Docker services or embedded SQLite/in-memory queues will be required if running locally. | Confirmed via `Get-Command psql, redis-cli` check. Docker daemon is installed but currently stopped. | Medium | PENDING DAEMON STARTUP |
| ASM-004 | 2026-09-28 | Codebase Heritage | The repository is a greenfield initialization with no pre-existing legacy code, scripts, or assets inherited from an earlier project. | Confirmed by initial git history and recursive workspace listing showing only audit documentation files. | Low | VERIFIED |
| ASM-005 | 2026-09-28 | Audit Log Privilege Enforcement | SQLite does not support SQL user-level GRANT/REVOKE privilege enforcement (e.g. revoking UPDATE/DELETE on `audit_logs`). Append-only security is enforced by application logic in SQLite and marked pending PostgreSQL for database-level role enforcement. | Documented architecture limitation of SQLite database engine. | Low | VERIFIED (LIMITATION RECORDED) |
| ASM-006 | 2026-09-28 | Cross-Dialect Primary Key Typing | Using `BigInteger().with_variant(Integer, "sqlite")` enables SQLite to treat `id` as an autoincrementing ROWID alias while producing standard 64-bit BIGINT / BIGSERIAL on PostgreSQL. | Confirmed by SQLAlchemy 2.0 dialect specification and verified by automated CRUD test suite. | Low | VERIFIED |
| ASM-007 | 2026-09-28 | Official CCTV Integration Invariants | All cameras in the official Sentinel environment publish via RTSP (:8554), WebRTC/WHEP (:8889), and HLS; catalogue discovery via `GET /api/ingest` is the authoritative source for stream parameters. | Confirmed by official Sentinel technical contract provided in Phase 3 instructions. | Low | VERIFIED SPECIFICATION |
| ASM-008 | 2026-09-28 | Stream Host Provisioning | The actual stream host IP/domain is not provided in repository files or environment variables; the application must keep `SENTINEL_STREAM_HOST` unconfigured until supplied by organizers. | Confirmed by recursive file and environment search returning zero host matches. | Medium | VERIFIED (MARKED BLOCKED) |
| ASM-009 | 2026-09-28 | Leaflet Tile Provider Fallback | Public OpenStreetMap tiles (`https://tile.openstreetmap.org/{z}/{x}/{y}.png`) are used as development-safe default without commercial API keys. Tile load errors are explicitly caught and surfaced as `MAP TILES UNAVAILABLE`. | Required by Rule 18 & 19; confirmed by absence of commercial tile credentials. | Low | VERIFIED |
| ASM-010 | 2026-09-28 | Zero Synthetic GIS Points in Database | The production SQLite/PostgreSQL database strictly contains 0 synthetic GIS coordinates. Cameras without verified coordinates from `/api/ingest` remain `UNMAPPED` and are omitted from GeoJSON features. | Required by Phase 4 Rule 3 & 25; verified by `sentinel.db` camera row count (0 rows). | Low | VERIFIED |
| ASM-011 | 2026-09-28 | OpenCV VideoIO FFmpeg Backend | OpenCV 5.0.0 built-in `CAP_FFMPEG` videoio backend DLL is utilized for RTSP/TCP packet demuxing and H.264/H.265 decoding on Windows, satisfying Phase 5 requirements without requiring `ffmpeg.exe` in system PATH. | Verified via `cv2.videoio_registry.hasBackend(cv2.CAP_FFMPEG) == True`. | Low | VERIFIED |
| ASM-012 | 2026-09-28 | PTS Observation Clock Invariant | Authoritative observation time is strictly bound to stream PTS (`CAP_PROP_POS_MSEC`); system clock `time.monotonic()` is quarantined to internal connection watchdog and diagnostic metrics. | Required by Section 9 of Stage 5 Directive. | Low | VERIFIED |



---

## Prohibited Hallucinations (Explicitly Kept as UNKNOWN, NOT Assumed)

The following items are deliberately **NOT** assumed:
1. **Actual Sentinel Stream Host (`<host>`):** NOT ASSUMED. Marked `UNKNOWN / BLOCKED`. Never replaced with `localhost` or fake IPs.
2. **Camera Feeds & Real RTSP URLs:** NOT ASSUMED. Marked `UNKNOWN / BLOCKED`.
3. **Exact Live Catalogue Response Fields:** NOT ASSUMED. Parsed with flexible Pydantic `extra="allow"` model; marked `UNVERIFIED` until verified host response is captured.
4. **Government Police Database Schemas & Endpoints:** NOT ASSUMED. Marked `UNKNOWN`.
5. **Geographic Coordinates & Real Camera Locations:** NOT ASSUMED. Marked `UNKNOWN`.
6. **Accuracy / Inference Benchmarks:** NOT ASSUMED. Marked `UNKNOWN`.
