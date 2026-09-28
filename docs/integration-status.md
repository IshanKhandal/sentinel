# External Integration Register

> **Protocol Note:** In accordance with Project Rule 28, Phase 0/1/2 Directives, every external integration must be tracked below. Under no circumstances should endpoints, hosts, credentials, or schemas be fabricated.

| Integration | Purpose | Expected Source | Verified? | Endpoint / Resource | Authentication | Current Status | Evidence | Blocker |
|---|---|---|---|---|---|---|---|---|
| Git Remote Repository | Source control and collaboration | GitHub (`IshanKhandal/sentinel`) | YES | `https://github.com/IshanKhandal/sentinel.git` | Git Credential Manager / SSH | CONNECTED | Verified via `git remote -v`, `git push -u origin main` (code 0) | None |
| SQLite (Local Engine) | Development persistence for all 19 system tables | Local Python standard library `sqlite3` | YES | `sqlite:///./sentinel.db` | Local filesystem file permissions | VERIFIED WORKING | 19 tables created, migrations tested, 7 pytest tests passing | None |
| Alembic Migration Engine | Schema evolution, automated migrations, and drift checks | Python `alembic` package | YES | `alembic.ini` / `alembic/` | Local CLI access | VERIFIED WORKING | Clean initial migration, upgrade/downgrade/upgrade verified, zero schema drift | None |
| PostgreSQL (Production Target) | Enterprise relational and geospatial persistence | Remote / Containerized PostgreSQL 16 server | NO | `postgresql+psycopg2://...` | Database user/password credentials | IMPLEMENTED + UNTESTED | Schema written using cross-dialect types; PostgreSQL server not installed/running locally | PostgreSQL CLI not installed, Docker daemon stopped |
| Sentinel CCTV Streams | Ingestion of live or recorded surveillance video | Gujarat Police CCTV network / Hackathon test server | NO | UNKNOWN (DO NOT INVENT) | UNKNOWN | UNVERIFIED | Workspace search returned no stream URLs or credentials | No RTSP/HLS stream addresses or camera credentials provided |
| Police Watchlist / Vahan API | Vehicle registration and stolen/wanted vehicle lookup | Government transport / police database | NO | UNKNOWN (DO NOT INVENT) | UNKNOWN | UNVERIFIED | No API endpoints or schemas present in workspace | No API endpoints or access credentials provided |
| Map / GIS Tile Service | Rendering geospatial camera locations and vehicle routes | OpenStreetMap / Mapbox / Google Maps | NO | UNKNOWN | UNKNOWN | UNVERIFIED | No map tokens or tile endpoints configured | Awaiting provider decision and API keys |
| Model Weights Storage | Pre-trained weights for vehicle detection & ANPR | Ultralytics / Hugging Face / Custom storage | NO | UNKNOWN | UNKNOWN | UNVERIFIED | No weights or model files present in workspace | Model selection pending challenge specifications |

---

## Status Definitions
- **CONNECTED / VERIFIED WORKING:** Verified live connection, successful round-trip execution, and automated test passage.
- **IMPLEMENTED + UNTESTED:** Schema/adapter implemented to specification but underlying server environment is not present locally to test.
- **UNVERIFIED:** Resource exists conceptually or in specifications but has not been tested.
- **MOCKED:** Synthetic adapter in place with explicit isolation boundaries.
- **BLOCKED:** Cannot proceed due to missing endpoints, credentials, or network barriers.
