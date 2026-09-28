# Sentinel Definition of Done (DoD)

> **Document Status:** ARCHITECTURE FREEZE (Phase 1)  
> **Protocol Standard:** Non-Hallucination & Evidence-First Engineering Rules ([docs/engineering-rules.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/engineering-rules.md), Rule 7 & Rule 19)

A feature, module, or user story is considered **COMPLETE** if and only if **EVERY SINGLE ONE** of the following ten criteria is verified and backed by reproducible evidence:

---

## The 10 Mandatory Criteria

### 1. Concrete Implementation Exists
- Working code is committed to the repository.
- No stub functions that merely `pass` or return empty mock values in production code paths.
- Filenames and declarations alone do NOT constitute completion.

### 2. Backend Service Exists (Where Required)
- Operational REST endpoint or background worker exists.
- Business logic validates inputs, handles edge cases, and logs actions.

### 3. Frontend Integration Connected (Where Required)
- UI components make actual HTTP / WebSocket calls to the backend.
- UI reacts dynamically to real server responses and error codes.
- No hardcoded tables, static mock cards, or disconnected buttons.

### 4. Database Persistence Operates (Where Required)
- Data is successfully written to and read from the database.
- Foreign key constraints, unique constraints, and indexes are verified.
- Schema changes are managed via versioned migration scripts.

### 5. Error Handling & Edge Cases Covered
- Network drops, invalid input payloads, and unexpected timeouts return structured error envelopes (RFC 7807).
- Application does not crash or expose unhandled stack traces to client browsers.

### 6. Automated Tests Exist
- Unit tests written for core domain logic.
- Integration tests written for API endpoints and database operations.
- Test files located under standard test directories (`tests/`).

### 7. Tests Actually Pass
- Test runner output is inspected and confirmed clean (exit code 0).
- No suppressed errors or skipped assertions disguised as passing tests.

### 8. Zero Fake Functionality Presented as Live
- Strictly enforces Rule 6, 30, and 31.
- No simulated data or prerecorded video is ever badged as `LIVE` or `CONNECTED`.
- Watchlist matches and journeys are generated only from actual stored records.

### 9. Documentation Updated & Traced
- [docs/requirements-traceability.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/requirements-traceability.md) updated with implementation location and verification method.
- Any new assumptions recorded in [docs/assumptions.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/assumptions.md).

### 10. Operational Mode (DEMO vs. LIVE) Correctly Enforced
- System operates cleanly under both `DEMO` and `LIVE` configurations.
- In `LIVE` mode, missing integrations fail gracefully as `UNAVAILABLE` rather than falling back to mock data.
