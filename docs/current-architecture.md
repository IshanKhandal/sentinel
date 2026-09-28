# Current Architecture Baseline (Phase 0 Forensic Audit)

> **Protocol Note:** In accordance with Project Rule 7, 8, 11, and Phase 0 Directive 13, this document records ONLY the architecture that ACTUALLY EXISTS in the repository as of the forensic audit on 2026-09-28.

## 1. System Inventory

```text
[Repository Root: c:\Users\ishan\sentinel gujarat hackathon]
 ├── .git/                        (Git repository connected to https://github.com/IshanKhandal/sentinel.git)
 ├── .gitignore                   (Filters dependencies, build artifacts, and secret files)
 ├── README.md                    (Project overview and rule index)
 └── docs/
     ├── engineering-rules.md     (Codified Rules 1–43 and Final Rule)
     ├── requirements-traceability.md (Traceability matrix)
     ├── assumptions.md           (Active assumptions log)
     ├── integration-status.md    (External integrations register)
     ├── demo-mode.md             (Simulation boundaries and data states)
     ├── sentinel-requirements.md (Requirements baseline)
     ├── current-architecture.md  (This document)
     ├── sentinel-target-architecture.md (Target design)
     └── sentinel-gap-analysis.md (Gap analysis)
```

## 2. Component Forensic Audit

| Subsystem | Existing Implementation | Language / Tech | Execution State | Evidence |
|---|---|---|---|---|
| **Frontend UI** | None | N/A | NON-EXISTENT | Workspace search reveals zero `.html`, `.js`, `.jsx`, `.ts`, `.tsx`, or `.vue` files. |
| **Backend API** | None | N/A | NON-EXISTENT | Zero server files (`server.py`, `app.py`, `main.py`, `index.js`, etc.). |
| **Database** | None | N/A | NON-EXISTENT | No SQLite `.db` files, no Prisma/SQLAlchemy/Django schemas, no migration files. Local PostgreSQL/Redis CLI not present. |
| **AI / Computer Vision** | None | N/A | NON-EXISTENT | No inference code, no PyTorch/TensorFlow/OpenCV scripts, no model weight files (`.pt`, `.onnx`, `.engine`). |
| **Streaming / CCTV** | None | N/A | NON-EXISTENT | No RTSP ingestion, GStreamer pipelines, or FFmpeg wrappers. FFmpeg is not installed on the system PATH. |
| **GIS / Mapping** | None | N/A | NON-EXISTENT | No Leaflet, Mapbox, or GIS coordinates code. |
| **Authentication & RBAC** | None | N/A | NON-EXISTENT | No auth routes, JWT configs, or user models. |
| **Containerization** | None | N/A | NON-EXISTENT | No `Dockerfile` or `docker-compose.yml` present in workspace. Docker Desktop is installed but daemon is stopped. |

## 3. Verified Host Environment

- **Operating System:** Windows 64-bit
- **Shell:** PowerShell
- **Node.js:** `v24.16.0` (Installed)
- **npm:** `11.13.0` (Installed)
- **Python:** `3.14.3` (Installed)
- **Docker Client:** `29.5.3` (Installed; engine daemon stopped)
- **FFmpeg:** Not installed in PATH (`CommandNotFoundException`)
- **Database CLIs:** `psql` and `redis-cli` not installed in PATH

## 4. Architectural Summary

The project is currently at **Stage 0 (Greenfield / Governance Initialization)**. There are no legacy code artifacts, pre-existing police prototypes, or inherited modules in this repository. All subsequent architecture must be built from the ground up following evidence-first specifications.
