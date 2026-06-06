"""Shared helpers for picking plate-like digit runs from OCR output."""

from __future__ import annotations

import re

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

_MIN_PLATE_DIGITS = 4
_MAX_PLATE_DIGITS = 8
_IDEAL_PLATE_LEN = 5.5

# Digits separated by spaces/dashes, e.g. "1 9 7 5 3" on Iraqi plates.
_SPACED_DIGITS = re.compile(r"(?:\d[\s.\-/،|]*){3,}\d")


def normalize_digits(text: str) -> str:
    return text.translate(_AR_DIGITS)


def digit_runs(text: str, *, min_len: int = 3) -> list[str]:
    """Split text into separate contiguous digit runs (Arabic-Indic → Latin)."""
    norm = normalize_digits(text)
    runs: list[str] = []
    current = ""
    for ch in norm:
        if ch.isdigit():
            current += ch
        else:
            if len(current) >= min_len:
                runs.append(current)
            current = ""
    if len(current) >= min_len:
        runs.append(current)
    return runs


def spaced_digit_plates(text: str) -> list[str]:
    """Extract plate numbers where OCR put spaces between digits (1 9 7 5 3)."""
    norm = normalize_digits(text)
    plates: list[str] = []
    for match in _SPACED_DIGITS.finditer(norm):
        digits = re.sub(r"\D", "", match.group())
        if _MIN_PLATE_DIGITS <= len(digits) <= _MAX_PLATE_DIGITS:
            plates.append(digits)
    return plates


def runs_from_text(text: str, confidence: float) -> list[tuple[str, float]]:
    """All plate-like digit runs from one OCR string."""
    runs: list[tuple[str, float]] = []
    seen: set[str] = set()
    for digits in (*digit_runs(text), *spaced_digit_plates(text)):
        if digits not in seen:
            seen.add(digits)
            runs.append((digits, confidence))
    return runs


def score_plate_digits(digits: str, confidence: float) -> float:
    """Score a digit string for how plate-like it is (length + confidence)."""
    n = len(digits)
    if n < _MIN_PLATE_DIGITS:
        return -1.0
    if n > 10:
        return -1.0

    len_score = max(0.0, 1.0 - abs(n - _IDEAL_PLATE_LEN) / 3.0)
    if n > _MAX_PLATE_DIGITS:
        len_score *= max(0.1, 1.0 - (n - _MAX_PLATE_DIGITS) * 0.35)

    conf = confidence / 100.0 if confidence > 1.0 else confidence
    return len_score * 0.35 + conf * 0.65


def pick_best_digits(runs: list[tuple[str, float]]) -> tuple[str, float]:
    """Pick the most plate-like digit run from (digits, confidence) pairs."""
    if not runs:
        return "", 0.0
    scored = [
        (digits, conf, score_plate_digits(digits, conf))
        for digits, conf in runs
        if len(digits) >= 3
    ]
    if not scored:
        return "", 0.0

    best_digits, best_conf, best_score = max(scored, key=lambda item: item[2])

    # EasyOCR often reads "9753" strongly but misses a leading "1" from "1 9 7 5 3".
    # Prefer a longer run that ends with the current best (e.g. 19753 ⊃ 9753).
    for digits, conf, score in scored:
        if len(digits) <= len(best_digits):
            continue
        if not digits.endswith(best_digits):
            continue
        if score >= best_score * 0.55:
            best_digits, best_conf, best_score = digits, conf, score

    return best_digits, best_conf
