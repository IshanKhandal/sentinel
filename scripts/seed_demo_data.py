"""Idempotent demonstration environment seeder for Sentinel Gujarat.

Protocol Standards:
- docs/engineering-rules.md (Rules 23, 24, 25, 36)
- docs/demo-mode.md (Explicit DEMO labeling, zero coordinate hallucination, explicit UNMAPPED handling)
- Stages 1-17 End-to-End Verification Pipeline
"""

import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from backend.app.db.session import SessionLocal
from backend.app.core.security import hash_password
from backend.app.core.permissions import (
    seed_roles_and_permissions,
    ROLE_SUPER_ADMIN,
    ROLE_INVESTIGATOR,
    ROLE_OPERATOR,
    ROLE_AUDITOR,
)
from backend.app.models.access import Department, Role, User
from backend.app.models.surveillance import Location, Camera
from backend.app.models.intelligence import Detection, Vehicle
from backend.app.models.watchlists import Watchlist, WatchlistEntry
from backend.app.models.alerts import Alert
from backend.app.models.investigation import Investigation, InvestigationEvent
from backend.app.models.audit import AuditLog


def seed_demo_environment(db: Session) -> dict:
    """Seed foundational demo users, cameras, observations, alerts, and investigations."""
    # 1. Seed Roles & Permissions
    seed_roles_and_permissions(db)
    roles = {r.name: r for r in db.query(Role).all()}

    # 2. Departments
    dept_hq = db.query(Department).filter_by(code="GJ-POL-HQ").first()
    if not dept_hq:
        dept_hq = Department(
            id=uuid.uuid4(),
            name="Gujarat Police Command & Control HQ",
            code="GJ-POL-HQ",
        )
        db.add(dept_hq)

    dept_amd = db.query(Department).filter_by(code="GJ-AMD-TRAFFIC").first()
    if not dept_amd:
        dept_amd = Department(
            id=uuid.uuid4(),
            name="Ahmedabad City Traffic Branch",
            code="GJ-AMD-TRAFFIC",
        )
        db.add(dept_amd)
    db.commit()

    # 3. Standard Users (SuperAdmin, Investigator, Operator, Auditor)
    demo_users_spec = [
        {
            "badge": "SYS001",
            "name": "Sentinel System Administrator",
            "email": "admin@sentinel.internal",
            "password": "SentinelAdmin2026!",
            "role": ROLE_SUPER_ADMIN,
            "dept": dept_hq,
        },
        {
            "badge": "INV001",
            "name": "Inspector Vikram Patel",
            "email": "investigator@sentinel.internal",
            "password": "SentinelTest2026!",
            "role": ROLE_INVESTIGATOR,
            "dept": dept_amd,
        },
        {
            "badge": "OP001",
            "name": "Operator Rajesh Sharma",
            "email": "operator@sentinel.internal",
            "password": "SentinelTest2026!",
            "role": ROLE_OPERATOR,
            "dept": dept_amd,
        },
        {
            "badge": "AUD001",
            "name": "Auditor Meera Desai",
            "email": "auditor@sentinel.internal",
            "password": "SentinelTest2026!",
            "role": ROLE_AUDITOR,
            "dept": dept_hq,
        },
    ]

    users = {}
    for spec in demo_users_spec:
        user = db.query(User).filter_by(badge_number=spec["badge"]).first()
        if not user:
            user = User(
                id=uuid.uuid4(),
                badge_number=spec["badge"],
                full_name=spec["name"],
                email=spec["email"],
                hashed_password=hash_password(spec["password"]),
                role_id=roles[spec["role"]].id,
                department_id=spec["dept"].id,
                is_active=True,
            )
            db.add(user)
            db.flush()
        users[spec["role"]] = user
    db.commit()

    # 4. Locations & Cameras (WGS84 verified coordinates in Gujarat)
    locations_spec = [
        {
            "name": "SG Highway Junction (Pakwan)",
            "city": "Ahmedabad",
            "lat": 23.0338,
            "lon": 72.5078,
            "cam_name": "CAM-AMD-SG01",
            "stream_type": "DEMO",
            "rtsp": "rtsp://demo.sentinel.internal/amd-sg01",
        },
        {
            "name": "ISKCON Cross Road",
            "city": "Ahmedabad",
            "lat": 23.0278,
            "lon": 72.5085,
            "cam_name": "CAM-AMD-IS02",
            "stream_type": "DEMO",
            "rtsp": "rtsp://demo.sentinel.internal/amd-is02",
        },
        {
            "name": "Gandhinagar Secretariat Gate 1",
            "city": "Gandhinagar",
            "lat": 23.2156,
            "lon": 72.6369,
            "cam_name": "CAM-GND-SC01",
            "stream_type": "DEMO",
            "rtsp": "rtsp://demo.sentinel.internal/gnd-sc01",
        },
        {
            "name": "Vadodara Express Highway Junction",
            "city": "Vadodara",
            "lat": 22.3072,
            "lon": 73.1812,
            "cam_name": "CAM-BRD-EX01",
            "stream_type": "DEMO",
            "rtsp": "rtsp://demo.sentinel.internal/brd-ex01",
        },
        {
            "name": "Unmapped Surveillance Post #9",
            "city": "Surat",
            "lat": None,
            "lon": None,
            "cam_name": "CAM-SRT-UNMAPPED",
            "stream_type": "DEMO",
            "rtsp": "rtsp://demo.sentinel.internal/srt-unmapped",
        },
    ]

    cameras = {}
    for spec in locations_spec:
        loc = db.query(Location).filter_by(name=spec["name"]).first()
        if not loc:
            loc = Location(
                id=uuid.uuid4(),
                name=spec["name"],
                city=spec["city"],
                latitude=spec["lat"],
                longitude=spec["lon"],
            )
            db.add(loc)
            db.flush()

        cam = db.query(Camera).filter_by(name=spec["cam_name"]).first()
        if not cam:
            cam = Camera(
                id=uuid.uuid4(),
                name=spec["cam_name"],
                department_id=dept_amd.id,
                location_id=loc.id,
                rtsp_url=spec["rtsp"],
                stream_type=spec["stream_type"],
                status="DEMO" if spec["lat"] is not None else "OFFLINE",
            )
            db.add(cam)
            db.flush()
        cameras[spec["cam_name"]] = cam
    db.commit()

    # 5. Demonstration Hotlist / Watchlist
    watchlist = db.query(Watchlist).filter_by(name="Stolen Commercial & Private Vehicles").first()
    if not watchlist:
        watchlist = Watchlist(
            id=uuid.uuid4(),
            name="Stolen Commercial & Private Vehicles",
            category="STOLEN",
            severity="CRITICAL",
            is_active=True,
            created_by_user_id=users[ROLE_SUPER_ADMIN].id,
        )
        db.add(watchlist)
        db.flush()

        entry = WatchlistEntry(
            id=uuid.uuid4(),
            watchlist_id=watchlist.id,
            plate_number="GJ01AB1234",
            vehicle_make_model="Maruti Swift White",
            fir_number="FIR-204/2026",
            notes="Vehicle reported stolen under FIR 204/2026 at Satellite Police Station",
            is_active=True,
        )
        db.add(entry)
        db.commit()
    else:
        entry = db.query(WatchlistEntry).filter_by(watchlist_id=watchlist.id, plate_number="GJ01AB1234").first()

    # 6. Demonstration Vehicle Observations (GJ01AB1234 cross-camera journey)
    now = datetime.now(timezone.utc)
    target_plate = "GJ01AB1234"

    existing_detections = db.query(Detection).filter_by(plate_number=target_plate).all()
    if not existing_detections:
        cams_seq = [
            (cameras["CAM-AMD-SG01"], now - timedelta(minutes=30)),
            (cameras["CAM-AMD-IS02"], now - timedelta(minutes=20)),
            (cameras["CAM-GND-SC01"], now - timedelta(minutes=5)),
        ]

        detections = []
        for cam, obs_time in cams_seq:
            det = Detection(
                id=uuid.uuid4(),
                camera_id=cam.id,
                detected_at=obs_time,
                plate_number=target_plate,
                raw_text=target_plate,
                confidence_vehicle=0.96,
                confidence_plate=0.94,
                vehicle_type="car",
                bbox_vehicle=[120, 240, 450, 520],
                snapshot_path="/snapshots/demo_car_01.jpg",
                is_demo=True,
            )
            db.add(det)
            detections.append(det)
        db.commit()

        # 7. Create Alert for the match
        alert = Alert(
            id=uuid.uuid4(),
            watchlist_entry_id=entry.id,
            detection_id=detections[-1].id,
            camera_id=cameras["CAM-GND-SC01"].id,
            plate_number=target_plate,
            severity="CRITICAL",
            status="NEW",
            created_at=now - timedelta(minutes=4),
        )
        db.add(alert)
        db.commit()

        # 8. Investigation Case
        inv = Investigation(
            id=uuid.uuid4(),
            case_number="INV-2026-0042",
            title="Grand Theft Auto: Inter-City Vehicle Interception",
            description="Active investigation regarding stolen vehicle GJ01AB1234 tracked moving between Ahmedabad and Gandhinagar.",
            status="IN_PROGRESS",
            target_plate=target_plate,
            lead_detective_id=users[ROLE_INVESTIGATOR].id,
        )
        db.add(inv)
        db.flush()

        # Attach last observation as event
        inv_event = InvestigationEvent(
            id=uuid.uuid4(),
            investigation_id=inv.id,
            detection_id=detections[-1].id,
            sequence_order=1,
            notes="Vehicle positively identified passing Gandhinagar Secretariat surveillance point.",
        )
        db.add(inv_event)
        db.commit()

    # 9. Audit Log for demo seeding
    audit_init = db.query(AuditLog).filter_by(action="SYSTEM_INIT_DEMO").first()
    if not audit_init:
        audit_init = AuditLog(
            user_id=users[ROLE_SUPER_ADMIN].id,
            badge_number="SYS001",
            action="SYSTEM_INIT_DEMO",
            resource_type="SYSTEM",
            resource_id="sentinel-gujarat",
            ip_address="127.0.0.1",
            payload_summary='{"status": "Demo environment successfully seeded with verified WGS84 coordinates"}',
        )
        db.add(audit_init)
        db.commit()

    return {
        "status": "SEEDED",
        "users": len(users),
        "cameras": len(cameras),
    }


if __name__ == "__main__":
    db = SessionLocal()
    try:
        res = seed_demo_environment(db)
        print("Demo seeding result:", res)
    finally:
        db.close()
