# Requirements Traceability Matrix

> **Protocol Note:** In accordance with Project Rule 26 and Phase 0/1/2 Directives, every major requirement must be tracked here with verified evidence, implementation paths, verification methods, and strict status.
> 
> Allowed Statuses: `VERIFIED` | `IMPLEMENTED + TESTED` | `IMPLEMENTED + UNTESTED` | `PARTIAL` | `BLOCKED` | `UNKNOWN`

| Requirement | Source | Evidence | Current Implementation | Implementation Location | Verification Method | Status |
|---|---|---|---|---|---|---|
| Adhere to 43 Evidence-First Engineering Rules | User Project Charter | Explicit user rules prompt | Documented and codified | [docs/engineering-rules.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/engineering-rules.md) | File review and compliance audit | VERIFIED |
| Phase 0 Forensic Repository Audit | User Phase 0 Directive | User Phase 0 audit prompt | Completed forensic inspection and reports | [docs/](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/) | Comprehensive file, runtime, and git checks | IMPLEMENTED + TESTED |
| Phase 1 Architecture Freeze | User Phase 1 Directive | Frozen specifications | Complete architecture contracts | [docs/](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/) | Specification review against project rules | VERIFIED |
| Database Persistence Engine (SQLite Local) | Phase 2 Directive & docs/database-design.md | SQLAlchemy 2.0 ORM models, session management, and SQLite WAL pragma | 19 normalized tables implemented | [backend/app/models/](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/backend/app/models/) | Automated Pytest suite (7 passed) & Alembic cycle | IMPLEMENTED + TESTED |
| Database Migration Lifecycle (Alembic) | Phase 2 Directive | Clean initial migration script `c1a5639ce6ba_initial_schema.py` | Upgrade, downgrade, re-upgrade, and drift check | [alembic/](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/alembic/) | `alembic upgrade head`, `downgrade base`, `alembic check` | IMPLEMENTED + TESTED |
| Critical Database Indexes (6 Required) | docs/database-design.md & Phase 2 Directive | Explicit index definitions in SQLAlchemy models | 6 required + 25 additional indexes created | [backend/app/models/](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/backend/app/models/) | Pytest index inspection against Base.metadata & SQLite engine | IMPLEMENTED + TESTED |
| Database Production Target (PostgreSQL) | Phase 2 Directive & docs/database-design.md | PostgreSQL-compatible schema types (BigInteger, Uuid, JSON) | Compatible schema implemented | [backend/app/models/](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/backend/app/models/) | Schema inspection (PostgreSQL server not installed locally) | IMPLEMENTED + UNTESTED |
| Audit Log Append-Only Schema Structure | docs/security-architecture.md & Phase 2 Directive | Immutable table structure with user, badge, action, timestamp | `audit_logs` table implemented | [backend/app/models/audit.py](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/backend/app/models/audit.py) | Pytest CRUD assertion (SQLite privilege enforcement limitation documented) | IMPLEMENTED + TESTED |
| Camera Registry Service (CRUD APIs) | Phase 1 Implementation Plan (Stage 3) | Planned next stage | None (Deferred to Stage 3) | None | N/A | UNKNOWN |
| CCTV / Video Stream Ingestion (RTSP/HLS/WebRTC) | Forensic Audit Item 3 | User query regarding existing CCTV code | None | None | Workspace search (`Get-ChildItem -Recurse`) | UNKNOWN |
| Vehicle Detection & ANPR / OCR | Forensic Audit Item 3 | User query regarding existing AI/ML code | None | None | Workspace search | UNKNOWN |
| Vehicle Tracking & Route Reconstruction | Forensic Audit Item 3 | User query regarding tracking / GIS | None | None | Workspace search | UNKNOWN |
| Watchlist Matching & Alert System | Forensic Audit Item 3 | User query regarding alerts / watchlists | None | None | Workspace search | UNKNOWN |
| Frontend Web UI & Dashboard | Forensic Audit Item 4 | User query regarding frontend UI | None | None | Workspace search | UNKNOWN |
| Backend API & WebSocket Server | Forensic Audit Item 5 | User query regarding backend framework | None | None | Workspace search | UNKNOWN |
| Gujarat Hackathon Official Problem Statement | Hackathon organizers | No brief/video/docs provided in repo yet | None | None | Workspace search | BLOCKED |
