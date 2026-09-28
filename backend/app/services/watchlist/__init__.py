"""Watchlist management and deterministic plate matching services.

Protocol Standards:
- Stage 9 Directive Sections 4, 6, 7, 8, 9, 12, 13, 14, 15, 16.
- Strict Stage 10 Alert Engine boundary: NO alerts generated or threat scoring performed.
"""

from backend.app.services.watchlist.matcher import (
    WatchlistMatcher,
    clean_plate_text,
    levenshtein_distance,
    string_similarity,
)
from backend.app.services.watchlist.service import (
    WatchlistService,
    WatchlistServiceError,
    WatchlistNotFoundError,
    WatchlistDuplicateError,
    WatchlistEntryDuplicateError,
    WatchlistValidationError,
    get_or_create_system_user,
)

__all__ = [
    "WatchlistMatcher",
    "WatchlistService",
    "WatchlistServiceError",
    "WatchlistNotFoundError",
    "WatchlistDuplicateError",
    "WatchlistEntryDuplicateError",
    "WatchlistValidationError",
    "get_or_create_system_user",
    "clean_plate_text",
    "levenshtein_distance",
    "string_similarity",
]
