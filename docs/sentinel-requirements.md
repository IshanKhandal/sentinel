# Sentinel Requirements Specification

> **Verification Standard:** Non-Hallucination & Evidence-First Engineering Protocol (Rule 24 & Rule 25).
> **Current Evidence Baseline:** As of 2026-09-28 forensic audit, no official challenge problem brief, PDF, video recording, or transcript file exists in the workspace. All challenge-specific requirements that have not been directly supplied are classified strictly as `UNKNOWN`.

---

## 1. MANDATORY REQUIREMENTS
*Requirements directly confirmed or mandated by current project charter:*

| ID | Requirement | Provenance | Verification Status | Notes |
|---|---|---|---|---|
| REQ-MAN-01 | Strict Adherence to Non-Hallucination & Evidence-First Engineering Rules | User Project Charter (Rules 1–43, Final Rule) | VERIFIED | Formally codified in [docs/engineering-rules.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/engineering-rules.md). Mandatory across all phases. |
| REQ-MAN-02 | Forensic Traceability & Continuous Documentation Maintenance | User Project Charter (Rules 26–29) | VERIFIED | Maintain requirements matrix, assumptions log, integration register, and demo boundary specs. |
| REQ-MAN-03 | Trustworthy UI State Reporting | User Project Charter (Rules 30–36) | VERIFIED | Mandatory states: `LIVE`, `DEMO`, `OFFLINE`, `UNKNOWN`, `UNAVAILABLE`. Never display simulated or unverified data as live. |
| REQ-MAN-04 | Specific Sentinel Hackathon Core Problem Statement & Workflow | Gujarat Police / Sentinel Challenge Organizers | UNKNOWN | Awaiting official brief/video/documentation. |

---

## 2. BONUS REQUIREMENTS

| ID | Requirement | Provenance | Verification Status | Notes |
|---|---|---|---|---|
| REQ-BON-01 | Challenge Bonus Criteria (e.g., edge deployment, specialized OCR, cross-camera ReID) | Gujarat Police / Sentinel Challenge Organizers | UNKNOWN | Cannot be confirmed until official hackathon evaluation criteria or bonus rubrics are supplied. |

---

## 3. TECHNICAL INTEGRATION REQUIREMENTS

| ID | Requirement | Provenance | Verification Status | Notes |
|---|---|---|---|---|
| REQ-INT-01 | Version Control Integration | Repository Config | VERIFIED | Remote tracking established with `https://github.com/IshanKhandal/sentinel.git` on branch `main`. |
| REQ-INT-02 | CCTV / RTSP / Video Stream Ingestion Interface | Inferred domain scope (Audit Item 3) | UNKNOWN | Actual stream URLs, codecs, protocol types (RTSP, HLS, WebRTC), and camera network topologies are unverified. |
| REQ-INT-03 | Database Storage Engine | Inferred domain scope (Audit Item 3) | UNKNOWN | Database choice (PostgreSQL / SQLite / other) and host connection parameters are not yet provided. |
| REQ-INT-04 | External Police / Government API Integration | Inferred domain scope (Rule 2) | UNKNOWN | No official police API endpoints or specifications exist in the workspace. |

---

## 4. SUBMISSION REQUIREMENTS

| ID | Requirement | Provenance | Verification Status | Notes |
|---|---|---|---|---|
| REQ-SUB-01 | Git Repository with Full Commit History | Git remote origin | VERIFIED | Main branch repository hosted on GitHub. |
| REQ-SUB-02 | Complete Forensic Phase 0 Audit | User Directive (Phase 0) | VERIFIED | Forensic audit of current repo state, documentation files, gap analysis, and target architecture. |
| REQ-SUB-03 | Hackathon Submission Deliverables (Deck, Demo Video, Deployment) | Hackathon Organizers | UNKNOWN | Specific portal, deadline, format, and evaluation rubric are unverified. |

---

## 5. SCALABILITY REQUIREMENTS

| ID | Requirement | Provenance | Verification Status | Notes |
|---|---|---|---|---|
| REQ-SCA-01 | No Unsubstantiated Scalability Claims | User Project Charter (Rule 11) | VERIFIED | Performance claims must be verified with reproducible benchmark logs. No theoretical numbers. |
| REQ-SCA-02 | Concurrent Stream / Inference Target Benchmarks | Hackathon Organizers | UNKNOWN | Target FPS, stream count, and hardware budget are unverified. |

---

## 6. SECURITY & SECRETS REQUIREMENTS

| ID | Requirement | Provenance | Verification Status | Notes |
|---|---|---|---|---|
| REQ-SEC-01 | Zero Secret Exposure | User Project Charter (Rule 41) | VERIFIED | Gitignore enforced; no secrets, tokens, or credentials may be logged, committed, or rendered in UI. |
| REQ-SEC-02 | Role-Based Access Control (RBAC) & Audit Trails | Inferred domain scope (Audit Item 3) | UNKNOWN | Police clearance levels, user roles, and audit retention policies are unverified. |

---

## 7. UNKNOWN ITEMS (Awaiting Official Materials)

```text
UNKNOWN:
1. Exact problem statement, theme, and scenario of the Sentinel Gujarat Hackathon.
2. Official video / presentation materials / transcript.
3. Provided sample video feeds, CCTV clips, or test RTSP streams.
4. Ground-truth datasets for vehicle detection, ANPR, or watchlist matching.
5. Evaluation metrics (e.g., mAP, precision, recall, latency constraints).
6. Hardware deployment constraints (Cloud GPU, local edge device, CPU-only).

REQUIRED TO VERIFY:
Official challenge document, task description, video recording link/transcripts, or dataset repository from the organizers.

BLOCKED BY:
Feature implementation and data model development cannot proceed safely without verified challenge specifications.
```
