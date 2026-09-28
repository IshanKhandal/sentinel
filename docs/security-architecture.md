# Sentinel Security & Governance Architecture

> **Document Status:** ARCHITECTURE FREEZE (Phase 1)  
> **Protocol Standard:** Non-Hallucination & Evidence-First Engineering Rules ([docs/engineering-rules.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/engineering-rules.md))  
> **Core Principle:** Defense-in-depth. Security is NEVER enforced solely through frontend checks. All authorization is validated cryptographically on every backend API request.

---

## 1. Authentication & Token Management

- **Credentials Storage:** Passwords hashed using `bcrypt` (work factor 12) with salt. Plaintext passwords are never logged, stored, or transmitted.
- **Token Mechanism:** Stateless JSON Web Tokens (JWT) signed with HMAC-SHA256 (`HS256`) or asymmetric `RS256`.
- **Token Claims:**
  ```json
  {
    "sub": "user-uuid-1042",
    "badge": "badge_1042",
    "role": "Investigator",
    "dept": "GJ-AMD-01",
    "exp": 1790620800,
    "iat": 1790592000
  }
  ```
- **Token Lifespan:** Access tokens valid for 8 hours (standard police duty shift). Refresh tokens stored as secure, HTTP-only, SameSite cookies.

---

## 2. Role-Based Access Control (RBAC) Matrix

| Resource / Action | SuperAdmin | Investigator | Operator | Auditor |
|---|---|---|---|---|
| View Live Cameras & Map | ALLOW | ALLOW | ALLOW | ALLOW |
| Acknowledge / Dismiss Alerts | ALLOW | ALLOW | ALLOW | DENY |
| Query Historical Detections | ALLOW | ALLOW | ALLOW | ALLOW |
| Enroll Plates in Watchlist | ALLOW | ALLOW | DENY | DENY |
| Create / Edit Investigation | ALLOW | ALLOW | DENY | DENY |
| Export Evidence Dossier (PDF/ZIP) | ALLOW | ALLOW | DENY | DENY |
| Manage Users & Roles | ALLOW | DENY | DENY | DENY |
| Inspect Audit Logs | ALLOW | DENY | DENY | ALLOW |

- **Enforcement:** Implemented via FastAPI dependency injection:
  ```python
  @router.post("/watchlists/{id}/entries", dependencies=[Depends(require_role(["SuperAdmin", "Investigator"]))])
  ```

---

## 3. Input Validation & Defense Against Injection

- **Schema Strictness:** All incoming REST payloads validated against Pydantic models with `extra = "forbid"` to reject unexpected fields.
- **SQL Injection Prevention:** 100% of database interactions executed via SQLAlchemy ORM parameterized queries. Raw string concatenation in SQL queries is strictly prohibited.
- **Path Traversal Protection:** Image snapshot and file download endpoints sanitize input filenames using `os.path.basename` and resolve paths against an absolute canonical storage root (`/media/`).

---

## 4. Rate Limiting & DoS Protection

- **Public Endpoints (Login):** Restricted to 5 requests per IP per minute using a sliding-window rate limiter. Returns HTTP 429 Too Many Requests.
- **Query Endpoints (Historical Search):** Restricted to 60 requests per user per minute. Hard cap of max 200 items per page enforced.

---

## 5. Audit Logging & Non-Repudiation

- **Immutable Audit Trail:** All state-changing operations (logins, watchlist additions, alert dismissals, evidence downloads) generate an asynchronous write to the `audit_logs` table.
- **Database Permissions:** The application database role is granted `INSERT` and `SELECT` only on `audit_logs`. `UPDATE` and `DELETE` commands are permanently revoked to prevent tampering.
- **Cryptographic Evidence Hashing:** Exported evidence dossiers have a SHA-256 integrity hash recorded at generation time to guarantee digital chain-of-custody for judicial proceedings.

---

## 6. Secrets Management (Rule 41 Compliance)

- **Zero Secret Exposure:** Credentials, database passwords, and JWT secret keys MUST be loaded from environment variables (`.env` file excluded via `.gitignore`).
- **Log Sanitization:** A custom logging filter intercepts log records and scrubs any fields named `password`, `token`, `secret`, `authorization`, or `key`.

---

## 7. Data Retention & Privacy Considerations

- **Raw Frame Retention:** Video frames from surveillance feeds are processed in transient memory; raw video is NOT permanently retained unless tied to an active detection or alert.
- **Detection Retention:** Routine vehicle detections (non-watchlist) purged after a configurable retention window (e.g., 90 days). Detections linked to open criminal investigations are retained indefinitely until case closure.
