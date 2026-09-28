"""Watchlist management and plate matching REST API endpoints.

Protocol Standards:
- docs/api-contract.md Section 8 (Watchlists).
- Stage 9 Directive Sections 4, 6, 7, 8, 9, 12, 13, 14, 15, 16, 17, 18.
- RFC 7807 compliant error responses.
- Stage 10 Alert Engine Boundary: NO alerts fired or created.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.models.intelligence import Detection
from backend.app.schemas.watchlist import (
    WatchlistCreate,
    WatchlistRead,
    WatchlistUpdate,
    WatchlistListResponse,
    WatchlistEntryCreate,
    WatchlistEntryRead,
    WatchlistEntryUpdate,
    WatchlistEntryListResponse,
    PlateMatchRequest,
    WatchlistMatchResult,
    WatchlistMatchResponse,
)
from backend.app.services.watchlist import (
    WatchlistMatcher,
    WatchlistService,
    WatchlistNotFoundError,
    WatchlistDuplicateError,
    WatchlistEntryDuplicateError,
    WatchlistValidationError,
)

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


# ============================================================================
# Watchlist Endpoints
# ============================================================================

@router.get("", response_model=WatchlistListResponse)
def list_watchlists(
    is_active: Optional[bool] = Query(default=None, description="Filter by active status"),
    category: Optional[str] = Query(default=None, description="Filter by category (STOLEN, WANTED, SUSPECT, EXPIRED)"),
    limit: int = Query(default=50, ge=1, le=200, description="Page limit (max 200)"),
    skip: int = Query(default=0, ge=0, description="Offset pagination"),
    db: Session = Depends(get_db)
) -> WatchlistListResponse:
    """List configured police watchlists with optional status and category filters."""
    items, total = WatchlistService.list_watchlists(
        db=db,
        is_active=is_active,
        category=category,
        limit=limit,
        skip=skip
    )

    response_items = []
    for wl in items:
        # Count active entries for each watchlist
        entries_count = len([e for e in wl.entries if e.is_active]) if wl.entries else 0
        response_items.append(
            WatchlistRead(
                id=wl.id,
                name=wl.name,
                category=wl.category,
                severity=wl.severity,
                is_active=wl.is_active,
                created_by_user_id=wl.created_by_user_id,
                created_at=wl.created_at,
                entries_count=entries_count,
            )
        )

    return WatchlistListResponse(total=total, items=response_items)


@router.post("", response_model=WatchlistRead, status_code=status.HTTP_201_CREATED)
def create_watchlist(
    payload: WatchlistCreate,
    db: Session = Depends(get_db)
) -> WatchlistRead:
    """Create a new police watchlist hotlist category."""
    try:
        wl = WatchlistService.create_watchlist(db=db, data=payload)
        return WatchlistRead(
            id=wl.id,
            name=wl.name,
            category=wl.category,
            severity=wl.severity,
            is_active=wl.is_active,
            created_by_user_id=wl.created_by_user_id,
            created_at=wl.created_at,
            entries_count=0,
        )
    except WatchlistDuplicateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc)
        ) from exc
    except WatchlistValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        ) from exc


@router.get("/{watchlist_id}", response_model=WatchlistRead)
def get_watchlist(
    watchlist_id: uuid.UUID,
    db: Session = Depends(get_db)
) -> WatchlistRead:
    """Retrieve details of a specific police watchlist by ID."""
    wl = WatchlistService.get_watchlist(db=db, watchlist_id=watchlist_id)
    if not wl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist '{watchlist_id}' not found."
        )

    entries_count = len([e for e in wl.entries if e.is_active]) if wl.entries else 0
    return WatchlistRead(
        id=wl.id,
        name=wl.name,
        category=wl.category,
        severity=wl.severity,
        is_active=wl.is_active,
        created_by_user_id=wl.created_by_user_id,
        created_at=wl.created_at,
        entries_count=entries_count,
    )


@router.patch("/{watchlist_id}", response_model=WatchlistRead)
def update_watchlist(
    watchlist_id: uuid.UUID,
    payload: WatchlistUpdate,
    db: Session = Depends(get_db)
) -> WatchlistRead:
    """Update metadata or toggle active state of a police watchlist."""
    try:
        wl = WatchlistService.update_watchlist(db=db, watchlist_id=watchlist_id, data=payload)
        entries_count = len([e for e in wl.entries if e.is_active]) if wl.entries else 0
        return WatchlistRead(
            id=wl.id,
            name=wl.name,
            category=wl.category,
            severity=wl.severity,
            is_active=wl.is_active,
            created_by_user_id=wl.created_by_user_id,
            created_at=wl.created_at,
            entries_count=entries_count,
        )
    except WatchlistNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc)
        ) from exc
    except WatchlistDuplicateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc)
        ) from exc


@router.delete("/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist(
    watchlist_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Delete a police watchlist and all its enrolled vehicle registration entries."""
    try:
        WatchlistService.delete_watchlist(db=db, watchlist_id=watchlist_id)
    except WatchlistNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc)
        ) from exc


# ============================================================================
# Watchlist Entry Endpoints (docs/api-contract.md Section 8)
# ============================================================================

@router.get("/{watchlist_id}/entries", response_model=WatchlistEntryListResponse)
def list_watchlist_entries(
    watchlist_id: uuid.UUID,
    is_active: Optional[bool] = Query(default=None, description="Filter by active status"),
    plate_search: Optional[str] = Query(default=None, description="Search by plate number"),
    limit: int = Query(default=50, ge=1, le=200, description="Page limit (max 200)"),
    skip: int = Query(default=0, ge=0, description="Offset pagination"),
    db: Session = Depends(get_db)
) -> WatchlistEntryListResponse:
    """List license plate registrations enrolled onto a specific watchlist."""
    wl = WatchlistService.get_watchlist(db=db, watchlist_id=watchlist_id)
    if not wl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist '{watchlist_id}' not found."
        )

    items, total = WatchlistService.list_entries(
        db=db,
        watchlist_id=watchlist_id,
        is_active=is_active,
        plate_search=plate_search,
        limit=limit,
        skip=skip
    )

    response_items = [
        WatchlistEntryRead(
            id=entry.id,
            watchlist_id=entry.watchlist_id,
            plate_number=entry.plate_number,
            vehicle_make_model=entry.vehicle_make_model,
            fir_number=entry.fir_number,
            notes=entry.notes,
            is_active=entry.is_active,
            created_at=entry.created_at,
            watchlist_name=wl.name,
            category=wl.category,
            severity=wl.severity,
        )
        for entry in items
    ]

    return WatchlistEntryListResponse(total=total, items=response_items)


@router.post("/{watchlist_id}/entries", response_model=WatchlistEntryRead, status_code=status.HTTP_201_CREATED)
def enroll_plate(
    watchlist_id: uuid.UUID,
    payload: WatchlistEntryCreate,
    db: Session = Depends(get_db)
) -> WatchlistEntryRead:
    """Enroll a target license plate onto a police watchlist (docs/api-contract.md Section 8)."""
    try:
        entry = WatchlistService.enroll_plate(db=db, watchlist_id=watchlist_id, data=payload)
        wl = entry.watchlist
        return WatchlistEntryRead(
            id=entry.id,
            watchlist_id=entry.watchlist_id,
            plate_number=entry.plate_number,
            vehicle_make_model=entry.vehicle_make_model,
            fir_number=entry.fir_number,
            notes=entry.notes,
            is_active=entry.is_active,
            created_at=entry.created_at,
            watchlist_name=wl.name if wl else None,
            category=wl.category if wl else None,
            severity=wl.severity if wl else None,
        )
    except WatchlistNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc)
        ) from exc
    except WatchlistEntryDuplicateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc)
        ) from exc
    except WatchlistValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        ) from exc


@router.get("/entries/{entry_id}", response_model=WatchlistEntryRead)
def get_watchlist_entry(
    entry_id: uuid.UUID,
    db: Session = Depends(get_db)
) -> WatchlistEntryRead:
    """Retrieve details of a single enrolled plate entry."""
    entry = WatchlistService.get_entry(db=db, entry_id=entry_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist entry '{entry_id}' not found."
        )

    wl = entry.watchlist
    return WatchlistEntryRead(
        id=entry.id,
        watchlist_id=entry.watchlist_id,
        plate_number=entry.plate_number,
        vehicle_make_model=entry.vehicle_make_model,
        fir_number=entry.fir_number,
        notes=entry.notes,
        is_active=entry.is_active,
        created_at=entry.created_at,
        watchlist_name=wl.name if wl else None,
        category=wl.category if wl else None,
        severity=wl.severity if wl else None,
    )


@router.patch("/entries/{entry_id}", response_model=WatchlistEntryRead)
def update_watchlist_entry(
    entry_id: uuid.UUID,
    payload: WatchlistEntryUpdate,
    db: Session = Depends(get_db)
) -> WatchlistEntryRead:
    """Update details or active state of an enrolled watchlist plate."""
    try:
        entry = WatchlistService.update_entry(db=db, entry_id=entry_id, data=payload)
        wl = entry.watchlist
        return WatchlistEntryRead(
            id=entry.id,
            watchlist_id=entry.watchlist_id,
            plate_number=entry.plate_number,
            vehicle_make_model=entry.vehicle_make_model,
            fir_number=entry.fir_number,
            notes=entry.notes,
            is_active=entry.is_active,
            created_at=entry.created_at,
            watchlist_name=wl.name if wl else None,
            category=wl.category if wl else None,
            severity=wl.severity if wl else None,
        )
    except WatchlistNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc)
        ) from exc
    except WatchlistEntryDuplicateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc)
        ) from exc
    except WatchlistValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        ) from exc


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist_entry(
    entry_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Delete an enrolled plate entry from its watchlist."""
    try:
        WatchlistService.delete_entry(db=db, entry_id=entry_id)
    except WatchlistNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc)
        ) from exc


# ============================================================================
# Stage 9 Watchlist Matching Endpoints
# ============================================================================

@router.post("/match-plate", response_model=WatchlistMatchResponse)
def match_plate_on_demand(
    payload: PlateMatchRequest,
    enable_fuzzy: Optional[bool] = Query(default=None, description="Override fuzzy matching toggle"),
    fuzzy_threshold: Optional[float] = Query(default=None, ge=0.0, le=1.0, description="Override similarity threshold"),
    fuzzy_max_distance: Optional[int] = Query(default=None, ge=0, le=5, description="Override max Levenshtein edit distance"),
    db: Session = Depends(get_db)
) -> WatchlistMatchResponse:
    """Evaluate an observed license plate string directly against all active watchlists.
    
    Strict Invariant: Does NOT trigger alert records in alerts table (Stage 10 owns alerts).
    """
    matches = WatchlistMatcher.match_plate(
        db=db,
        plate_number=payload.plate_number,
        raw_text=payload.raw_text,
        camera_id=payload.camera_id,
        video_pts_ms=payload.video_pts_ms,
        is_demo=payload.is_demo,
        ocr_confidence=payload.ocr_confidence,
        enable_fuzzy=enable_fuzzy,
        fuzzy_threshold=fuzzy_threshold,
        fuzzy_max_distance=fuzzy_max_distance,
    )

    return WatchlistMatchResponse(
        observed_plate=payload.plate_number,
        total_matches=len(matches),
        matches=matches,
        evaluated_at=datetime.now(timezone.utc),
    )


@router.post("/match-detection/{detection_id}", response_model=WatchlistMatchResponse)
def match_persisted_detection(
    detection_id: uuid.UUID,
    enable_fuzzy: Optional[bool] = Query(default=None, description="Override fuzzy matching toggle"),
    fuzzy_threshold: Optional[float] = Query(default=None, ge=0.0, le=1.0, description="Override similarity threshold"),
    fuzzy_max_distance: Optional[int] = Query(default=None, ge=0, le=5, description="Override max Levenshtein edit distance"),
    db: Session = Depends(get_db)
) -> WatchlistMatchResponse:
    """Evaluate a persisted Stage 8 detection against all active watchlists.
    
    Preserves all observation provenance (camera, PTS, raw text, detected timestamp).
    Strict Invariant: Does NOT trigger alert records in alerts table.
    """
    detection = db.query(Detection).filter(Detection.id == detection_id).first()
    if not detection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Detection '{detection_id}' not found."
        )

    matches = WatchlistMatcher.match_detection(
        db=db,
        detection=detection,
        enable_fuzzy=enable_fuzzy,
        fuzzy_threshold=fuzzy_threshold,
        fuzzy_max_distance=fuzzy_max_distance,
    )

    return WatchlistMatchResponse(
        observed_plate=detection.plate_number or "",
        total_matches=len(matches),
        matches=matches,
        evaluated_at=datetime.now(timezone.utc),
    )
