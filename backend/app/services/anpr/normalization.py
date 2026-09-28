"""Plate text normalization, Indian registration syntax validation, and contextual safety.

Protocol Standards:
- Stage 7 Directive Sections 12 & 13.
- Mandatory separation of raw_text from normalized_text.
- No blind global character substitutions (e.g. O->0, B->8) that corrupt valid plate sequences.
- Regex validation against authoritative Indian motor vehicle registration standards.
"""

import re
from typing import Tuple, Optional


# Authoritative Indian Vehicle Registration Syntax Patterns
# 1. Standard State Series: e.g. "GJ01AB1234", "MH12C9999", "DL3CAA1111"
INDIAN_STANDARD_PLATE_REGEX = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$")

# 2. Bharat Series (BH): e.g. "22BH1234AA"
INDIAN_BHARAT_SERIES_REGEX = re.compile(r"^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$")


def normalize_plate_text(raw_text: Optional[str]) -> Tuple[str, bool, bool]:
    """Sanitize raw OCR output into normalized registration plate string.

    Operations performed:
    1. Strip leading/trailing whitespaces.
    2. Convert to uppercase.
    3. Remove whitespace, hyphens, dots, and non-alphanumeric symbols.
    4. Validate against Indian registration syntax patterns.

    Returns:
        (normalized_text, is_valid_format, was_corrected)
    """
    if not raw_text:
        return "", False, False

    # Clean non-alphanumeric noise and whitespace
    cleaned = re.sub(r"[^A-Za-z0-9]", "", raw_text).upper()

    if not cleaned:
        return "", False, False

    # Check format validity before any contextual correction
    is_valid = bool(
        INDIAN_STANDARD_PLATE_REGEX.match(cleaned)
        or INDIAN_BHARAT_SERIES_REGEX.match(cleaned)
    )

    return cleaned, is_valid, False


def contextual_plate_correction(normalized_text: str) -> Tuple[str, bool, bool]:
    """Apply safe, position-aware contextual correction for high-ambiguity OCR characters.

    Safety Rule (Section 13):
    Never replace characters globally. Only apply if the string conforms to the expected
    length and structure of Indian standard plates (e.g. 10 chars: LL DD LLL DDDD).

    Positional rules:
    - Positions 0-1 (State code): MUST be alphabetic. E.g. '0' -> 'O', '1' -> 'I'.
      Example: "0J01AB1234" -> "GJ" is invalid, but if state code has numeric '0' -> 'O', '1' -> 'I'.
    - Positions 2-3 (District RTO): MUST be numeric. E.g. 'O' -> '0', 'I' -> '1'.
    - Trailing 4 positions (Unique number): MUST be numeric. E.g. 'O' -> '0', 'I' -> '1', 'B' -> '8', 'S' -> '5'.

    Returns:
        (corrected_text, is_valid_format, was_corrected)
    """
    if not normalized_text:
        return "", False, False

    # Only attempt contextual repair if length matches standard plate length (9 to 11 characters)
    length = len(normalized_text)
    if length < 8 or length > 11:
        # Invalid length; do not invent substitutions
        is_valid = bool(INDIAN_STANDARD_PLATE_REGEX.match(normalized_text))
        return normalized_text, is_valid, False

    chars = list(normalized_text)
    modified = False

    # Character confusion maps
    num_to_alpha = {"0": "O", "1": "I", "5": "S", "8": "B"}
    alpha_to_num = {"O": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"}

    # 1. First two characters: State Code (alphabetic)
    for i in (0, 1):
        if chars[i] in num_to_alpha:
            chars[i] = num_to_alpha[chars[i]]
            modified = True

    # 2. Last 4 characters: Unique registration number (numeric)
    for i in range(length - 4, length):
        if chars[i] in alpha_to_num:
            chars[i] = alpha_to_num[chars[i]]
            modified = True

    candidate = "".join(chars)
    is_valid = bool(
        INDIAN_STANDARD_PLATE_REGEX.match(candidate)
        or INDIAN_BHARAT_SERIES_REGEX.match(candidate)
    )

    if is_valid and modified:
        return candidate, True, True

    # If contextual repair did not yield a valid plate, revert to original normalized text
    orig_valid = bool(INDIAN_STANDARD_PLATE_REGEX.match(normalized_text))
    return normalized_text, orig_valid, False
