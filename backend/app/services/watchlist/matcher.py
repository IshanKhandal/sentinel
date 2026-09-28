"""Watchlist plate matching engine: exact & fuzzy deterministic matching.

Protocol Standards:
- docs/ai-architecture.md Section ANPR & Matching.
- docs/database-design.md Domain 4 (idx_watchlist_entries_plate_active).
- Stage 9 Directive Sections 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 19.
- Exact match takes strict precedence over fuzzy match.
- All matches preserve complete observation provenance.
- Inactive entries or inactive parent watchlists produce NO MATCH.
- ZERO alert generation or threat scoring (Stage 10 boundary strictly enforced).
"""

import re
import uuid
import logging
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.watchlists import Watchlist, WatchlistEntry
from backend.app.models.intelligence import Detection
from backend.app.schemas.watchlist import (
    WatchlistMatchResult,
    WatchlistMatchMethod,
)

logger = logging.getLogger("sentinel.watchlist.matcher")


def clean_plate_text(text: Optional[str]) -> str:
    """Normalize raw plate input according to Stage 7 ANPR contract.
    
    Removes whitespace, hyphens, and non-alphanumeric noise; converts to uppercase.
    Does NOT apply lossy global character substitutions.
    """
    if not text:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", text).strip().upper()


def levenshtein_distance(s1: str, s2: str) -> int:
    """Deterministic Wagner-Fischer algorithm for Levenshtein edit distance.
    
    Time complexity: O(len(s1) * len(s2))
    Space complexity: O(min(len(s1), len(s2)))
    """
    if s1 == s2:
        return 0
    if len(s1) == 0:
        return len(s2)
    if len(s2) == 0:
        return len(s1)

    if len(s1) < len(s2):
        s1, s2 = s2, s1

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def string_similarity(s1: str, s2: str) -> float:
    """Compute normalized string similarity score in range [0.0, 1.0].
    
    Formula: max(0.0, 1.0 - (edit_distance / max_len))
    """
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    dist = levenshtein_distance(s1, s2)
    return max(0.0, 1.0 - (dist / max_len))


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime has timezone set to UTC (handles SQLite naive timestamps)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class WatchlistMatcher:
    """State-free domain service for deterministic watchlist matching."""

    MATCHER_VERSION: str = "1.0.0"

    @classmethod
    def match_plate(
        cls,
        db: Session,
        plate_number: str,
        raw_text: Optional[str] = None,
        detection_id: Optional[uuid.UUID] = None,
        camera_id: Optional[uuid.UUID] = None,
        camera_name: Optional[str] = None,
        detected_at: Optional[datetime] = None,
        video_pts_ms: Optional[float] = None,
        is_demo: bool = False,
        ocr_confidence: Optional[float] = None,
        enable_fuzzy: Optional[bool] = None,
        fuzzy_threshold: Optional[float] = None,
        fuzzy_max_distance: Optional[int] = None,
    ) -> List[WatchlistMatchResult]:
        """Evaluate an observed plate against all active watchlist hotlists.
        
        Matching Pipeline:
        1. Plate Sanitization: Normalize input according to Stage 7 ANPR contract.
        2. Exact Matching: Query database index (idx_watchlist_entries_plate_active).
           Requires both WatchlistEntry.is_active == True AND Watchlist.is_active == True.
           If exact matches are found, return all matching entries immediately.
        3. Fuzzy Matching (if enabled and no exact match found):
           Query active entries and evaluate Levenshtein distance against candidate plates.
           Accept candidate if edit_distance <= max_distance AND similarity >= threshold.
        4. Return list of zero or more WatchlistMatchResult objects.
        
        Strict Non-Alert Invariant:
        Does NOT insert into `alerts` table or trigger notification dispatch.
        """
        clean_observed = clean_plate_text(plate_number)
        if not clean_observed:
            return []

        use_fuzzy = (
            enable_fuzzy
            if enable_fuzzy is not None
            else settings.WATCHLIST_FUZZY_MATCHING_ENABLED
        )
        threshold = (
            fuzzy_threshold
            if fuzzy_threshold is not None
            else settings.WATCHLIST_FUZZY_SIMILARITY_THRESHOLD
        )
        max_dist = (
            fuzzy_max_distance
            if fuzzy_max_distance is not None
            else settings.WATCHLIST_FUZZY_MAX_DISTANCE
        )

        # --------------------------------------------------------------------
        # Step 1: Indexed Exact Matching (Section 6, 19)
        # --------------------------------------------------------------------
        exact_query = (
            db.query(WatchlistEntry, Watchlist)
            .join(Watchlist, WatchlistEntry.watchlist_id == Watchlist.id)
            .filter(
                WatchlistEntry.plate_number == clean_observed,
                WatchlistEntry.is_active == True,
                Watchlist.is_active == True,
            )
        )
        exact_results = exact_query.all()

        utc_detected_at = ensure_utc(detected_at)

        if exact_results:
            matches: List[WatchlistMatchResult] = []
            for entry, wl in exact_results:
                match_item = WatchlistMatchResult(
                    match_id=str(uuid.uuid4()),
                    detection_id=detection_id,
                    camera_id=camera_id,
                    camera_name=camera_name,
                    detected_at=utc_detected_at,
                    video_pts_ms=video_pts_ms,
                    is_demo=is_demo,
                    observed_raw_plate=raw_text,
                    observed_normalized_plate=clean_observed,
                    watchlist_id=wl.id,
                    watchlist_name=wl.name,
                    watchlist_category=wl.category,
                    watchlist_severity=wl.severity,
                    watchlist_entry_id=entry.id,
                    matched_plate=entry.plate_number,
                    vehicle_make_model=entry.vehicle_make_model,
                    fir_number=entry.fir_number,
                    notes=entry.notes,
                    match_method=WatchlistMatchMethod.EXACT,
                    similarity_score=1.0,
                    edit_distance=0,
                    ocr_confidence=ocr_confidence,
                    matcher_version=cls.MATCHER_VERSION,
                )
                matches.append(match_item)
            return matches

        # --------------------------------------------------------------------
        # Step 2: Configurable Fuzzy Matching (Section 8, 9)
        # Only evaluated when no exact match exists and fuzzy matching enabled.
        # --------------------------------------------------------------------
        if not use_fuzzy:
            return []

        active_entries = (
            db.query(WatchlistEntry, Watchlist)
            .join(Watchlist, WatchlistEntry.watchlist_id == Watchlist.id)
            .filter(
                WatchlistEntry.is_active == True,
                Watchlist.is_active == True,
            )
            .all()
        )

        fuzzy_matches: List[WatchlistMatchResult] = []
        for entry, wl in active_entries:
            target_plate = entry.plate_number
            dist = levenshtein_distance(clean_observed, target_plate)
            
            if dist <= max_dist:
                sim = string_similarity(clean_observed, target_plate)
                if sim >= threshold:
                    match_item = WatchlistMatchResult(
                        match_id=str(uuid.uuid4()),
                        detection_id=detection_id,
                        camera_id=camera_id,
                        camera_name=camera_name,
                        detected_at=utc_detected_at,
                        video_pts_ms=video_pts_ms,
                        is_demo=is_demo,
                        observed_raw_plate=raw_text,
                        observed_normalized_plate=clean_observed,
                        watchlist_id=wl.id,
                        watchlist_name=wl.name,
                        watchlist_category=wl.category,
                        watchlist_severity=wl.severity,
                        watchlist_entry_id=entry.id,
                        matched_plate=target_plate,
                        vehicle_make_model=entry.vehicle_make_model,
                        fir_number=entry.fir_number,
                        notes=entry.notes,
                        match_method=WatchlistMatchMethod.FUZZY,
                        similarity_score=round(sim, 4),
                        edit_distance=dist,
                        ocr_confidence=ocr_confidence,
                        matcher_version=cls.MATCHER_VERSION,
                    )
                    fuzzy_matches.append(match_item)

        # Sort fuzzy matches by similarity score descending
        fuzzy_matches.sort(key=lambda m: (m.similarity_score, -m.edit_distance), reverse=True)
        return fuzzy_matches

    @classmethod
    def match_detection(
        cls,
        db: Session,
        detection: Detection,
        enable_fuzzy: Optional[bool] = None,
        fuzzy_threshold: Optional[float] = None,
        fuzzy_max_distance: Optional[int] = None,
    ) -> List[WatchlistMatchResult]:
        """Evaluate a persisted Stage 8 detection against all active watchlists.
        
        Preserves camera ID, camera name, detected_at, video_pts_ms, raw_text,
        and demo state directly from the persisted detection record.
        """
        if not detection.plate_number:
            return []

        pts_ms = None
        if isinstance(detection.detection_metadata, dict):
            pts_ms = detection.detection_metadata.get("video_pts_ms")

        cam_name = detection.camera.name if detection.camera else None

        return cls.match_plate(
            db=db,
            plate_number=detection.plate_number,
            raw_text=detection.raw_text,
            detection_id=detection.id,
            camera_id=detection.camera_id,
            camera_name=cam_name,
            detected_at=detection.detected_at,
            video_pts_ms=pts_ms,
            is_demo=detection.is_demo,
            ocr_confidence=detection.confidence_plate,
            enable_fuzzy=enable_fuzzy,
            fuzzy_threshold=fuzzy_threshold,
            fuzzy_max_distance=fuzzy_max_distance,
        )
