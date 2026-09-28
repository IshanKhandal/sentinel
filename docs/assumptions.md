# Project Assumptions Register

> **Protocol Note:** In accordance with Project Rule 27 and Phase 0/1/2 Directives, every assumption must be explicitly logged. Unrecorded assumptions are strictly forbidden. In all cases, `UNKNOWN` is preferred over `ASSUMED` unless strictly necessary for an environmental baseline.

## Active Assumptions Register

| ID | Date Recorded | Category | Stated Assumption | Empirical Basis / Justification | Risk Level | Status |
|---|---|---|---|---|---|---|
| ASM-001 | 2026-09-28 | Operating Environment | Host machine is 64-bit Windows with PowerShell shell, Node.js (`v24.16.0`), Python (`3.14.3`), and Docker CLI (`29.5.3`) available. | Confirmed via direct terminal inspection (`node -v`, `python --version`, `docker --version`). | Low | VERIFIED |
| ASM-002 | 2026-09-28 | Media Processing Tools | `ffmpeg` is not currently in system PATH and must either be installed locally or run via a containerized service. | Confirmed via `ffmpeg -version` failure (`CommandNotFoundException`). | Medium | VERIFIED |
| ASM-003 | 2026-09-28 | Database Availability | PostgreSQL and Redis CLI tools are not installed in system PATH; containerized Docker services or embedded SQLite/in-memory queues will be required if running locally. | Confirmed via `Get-Command psql, redis-cli` check. Docker daemon is installed but currently stopped. | Medium | PENDING DAEMON STARTUP |
| ASM-004 | 2026-09-28 | Codebase Heritage | The repository is a greenfield initialization with no pre-existing legacy code, scripts, or assets inherited from an earlier project. | Confirmed by initial git history and recursive workspace listing showing only audit documentation files. | Low | VERIFIED |
| ASM-005 | 2026-09-28 | Audit Log Privilege Enforcement | SQLite does not support SQL user-level GRANT/REVOKE privilege enforcement (e.g. revoking UPDATE/DELETE on `audit_logs`). Append-only security is enforced by application logic in SQLite and marked pending PostgreSQL for database-level role enforcement. | Documented architecture limitation of SQLite database engine. | Low | VERIFIED (LIMITATION RECORDED) |
| ASM-006 | 2026-09-28 | Cross-Dialect Primary Key Typing | Using `BigInteger().with_variant(Integer, "sqlite")` enables SQLite to treat `id` as an autoincrementing ROWID alias while producing standard 64-bit BIGINT / BIGSERIAL on PostgreSQL. | Confirmed by SQLAlchemy 2.0 dialect specification and verified by automated CRUD test suite. | Low | VERIFIED |

---

## Prohibited Hallucinations (Explicitly Kept as UNKNOWN, NOT Assumed)

The following items are deliberately **NOT** assumed:
1. **Camera Feeds & RTSP URLs:** NOT ASSUMED. Marked `UNKNOWN`.
2. **Detection Targets & Classes:** NOT ASSUMED. Marked `UNKNOWN`.
3. **Police Database Schemas & Endpoints:** NOT ASSUMED. Marked `UNKNOWN`.
4. **Geographic Coordinates & Map Projections:** NOT ASSUMED. Marked `UNKNOWN`.
5. **Accuracy / Inference Benchmarks:** NOT ASSUMED. Marked `UNKNOWN`.
