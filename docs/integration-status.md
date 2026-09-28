# Integration Status Log

> **Protocol Note:** In accordance with Project Rule 28, every external integration (APIs, RTSP camera streams, external models, cloud storage, database servers, government services) must be documented in this registry before or during implementation.

| Integration | Expected Source | Verified? | Endpoint / Resource | Authentication Requirement | Current Status | Evidence | Blockers |
|---|---|---|---|---|---|---|---|
| Git Remote Repository | GitHub (`IshanKhandal/sentinel`) | YES | `https://github.com/IshanKhandal/sentinel.git` | Git Credentials / SSH Key | CONNECTED | Verified via `git remote -v` and `git ls-remote` | None |
| Sentinel Problem Statement / Datasets | Gujarat Police Hackathon organizers | NO | UNKNOWN | UNKNOWN | UNVERIFIED | None provided in repo | Pending provision of challenge documents/links |
| Live CCTV / RTSP Feeds | Target deployment environment | NO | NONE | N/A | NONE | No real feeds provided | Live feeds do not exist in this environment |

---

## Verification Legend
- **VERIFIED:** Endpoint/resource pinged, authenticated, and tested with real payload.
- **CONNECTED:** Network connection established; full payload/schema testing pending.
- **UNVERIFIED:** Resource specified or hypothesized but not yet tested or available.
- **MOCKED / DEMO:** Simulated adapter in use; isolated from production path.
- **BLOCKED:** Integration cannot proceed due to missing credentials, endpoints, or network access.
