# Sentinel GIS & Geospatial Architecture

> **Document Status:** ARCHITECTURE FREEZE (Phase 1)  
> **Protocol Standard:** Non-Hallucination & Evidence-First Engineering Rules ([docs/engineering-rules.md](file:///c:/Users/ishan/sentinel%20gujarat%20hackathon/docs/engineering-rules.md))  
> **Mandatory Rule 37 & 38 Enforcement:** NEVER invent geographic coordinates or camera locations. Coordinates must originate from verified deployment configuration or be explicitly marked `DEMO_FIXTURE` in local testing.

---

## 1. Geospatial Data Standards

- **Coordinate Reference System:** WGS 84 (EPSG:4326) — standard GPS latitude/longitude.
- **Data Exchange Format:** GeoJSON (RFC 7946).
- **Frontend Mapping Library:** Leaflet.js / OpenStreetMap tile provider (no paid proprietary token dependencies required for core functionality).

---

## 2. Core GIS Subsystems

```text
┌──────────────────────────────────────────────────────────────┐
│                    GIS BACKEND SERVICE                       │
└──────────────────────────────┬───────────────────────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
    [Camera Markers &   [Route Rendering   [Radial Spatial
       Clustering]       & Trajectories]       Search]
            │                  │                  │
            └──────────────────┼──────────────────┘
                               │ (GeoJSON FeatureCollection)
                               ▼
┌──────────────────────────────────────────────────────────────┐
│             TACTICAL COMMAND MAP (Leaflet UI)                │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Component Details

### 3.1 Camera Markers & Dynamic Clustering
- **Marker Data Payload:**
  ```json
  {
    "type": "Feature",
    "geometry": {
      "type": "Point",
      "coordinates": [72.5714, 23.0305] // [Longitude, Latitude]
    },
    "properties": {
      "camera_id": "c1a2b3c4-0000-0000-0000-000000000001",
      "name": "Junction 04 - Ashram Road",
      "status": "DEMO",
      "stream_type": "DEMO",
      "heading": 180,
      "zone": "Ahmedabad West"
    }
  }
  ```
- **Clustering Strategy:** At wide zoom levels (city/district view, zoom < 14), markers are grouped using Leaflet.markercluster (Supercluster algorithm) to maintain 60 FPS UI rendering across dense camera grids.
- **Trustworthy Status Styling:**
  - `LIVE`: High-visibility Emerald Green marker with pulse animation.
  - `DEMO`: High-visibility Amber Orange marker with `[DEMO]` label badge.
  - `OFFLINE`: Neutral Grey marker with slash icon.
  - `UNMAPPED`: Displayed in side drawer with coordinates missing alert.

---

### 3.2 Vehicle Route Rendering & Trajectory Reconstruction
- **Route Assembly:** When an investigator requests a vehicle's journey (`GET /api/v1/vehicles/{plate}/journey`), the backend queries chronological camera detections.
- **GeoJSON LineString Generation:**
  ```json
  {
    "type": "Feature",
    "geometry": {
      "type": "LineString",
      "coordinates": [
        [72.5200, 23.0450], // Cam 1
        [72.5400, 23.0380], // Cam 2
        [72.5714, 23.0305]  // Cam 3
      ]
    },
    "properties": {
      "plate_number": "GJ01AB1234",
      "start_time": "2026-09-28T14:10:00Z",
      "end_time": "2026-09-28T14:45:00Z",
      "total_distance_km": 6.8
    }
  }
  ```
- **Temporal Direction Arrows:** Rendered along the trajectory line to show vehicle heading from first observation to latest.

---

### 3.3 Radial Geographic Search (Nearby Cameras)
- **Mathematical Formula:** Haversine formula implemented in pure Python / SQL (avoids mandatory PostGIS dependency during local SQLite development):
  $$d = 2r \arcsin\left(\sqrt{\sin^2\left(\frac{\Delta \phi}{2}\right) + \cos(\phi_1)\cos(\phi_2)\sin^2\left(\frac{\Delta \lambda}{2}\right)}\right)$$
  *(where $\phi$ is latitude in radians, $\lambda$ is longitude in radians, $r \approx 6371\text{ km}$)*.
- **Query Support:** Allows detectives to drop a pin on a crime scene and instantly query: "Retrieve all cameras within 1.5 km of this intersection."

---

### 3.4 Investigation Routes & Event Locations
- Detections associated with active investigations are highlighted with custom crime scene icons and timestamped event tooltips.
- Click-to-Inspect: Clicking a camera marker or route waypoint opens an instant media popover displaying the plate crop snapshot and detection confidence.
