"""EasyOCR-based reader for Arabic-Indic license-plate digits."""

from __future__ import annotations

import threading

import numpy as np

from .plate_digits import normalize_digits, pick_best_digits, runs_from_text, spaced_digit_plates

_reader = None
_lock = threading.Lock()
_failed = False


def is_available() -> bool:
    try:
        import easyocr  # noqa: F401
    except Exception:
        return False
    return True


def _get_reader():
    global _reader, _failed
    if _reader is not None or _failed:
        return _reader
    with _lock:
        if _reader is None and not _failed:
            try:
                import easyocr
                import torch

                use_gpu = torch.cuda.is_available()
                _reader = easyocr.Reader(["ar", "en"], gpu=use_gpu, verbose=False)
            except Exception:
                _failed = True
                _reader = None
    return _reader


def _assemble_top_row(results, img_h: int) -> tuple[str, float]:
    """Join digit boxes on the top row left→right (e.g. '1' + '9753' → '19753')."""
    if img_h <= 0:
        return "", 0.0
    boxes: list[tuple[float, str, float]] = []
    for box, text, prob in results:
        y_center = (box[0][1] + box[2][1]) / 2.0
        if y_center >= img_h * 0.55:
            continue
        digits = "".join(ch for ch in normalize_digits(text) if ch.isdigit())
        if not digits:
            continue
        x_left = min(p[0] for p in box)
        boxes.append((x_left, digits, float(prob)))

    if len(boxes) < 2:
        return "", 0.0

    # One box already holds most of the plate (e.g. "567955"). Joining a stray
    # leading digit from the grille ("8" + "567955") produces false 7-digit reads.
    if any(len(d) >= 5 for _, d, _ in boxes):
        return "", 0.0

    boxes.sort(key=lambda item: item[0])
    assembled = "".join(d for _, d, _ in boxes)
    if not (4 <= len(assembled) <= 8):
        return "", 0.0
    conf = float(np.mean([p for _, _, p in boxes])) * 100.0
    return assembled, conf


def _collect_runs_from_results(
    results, img_h: int, *, boost_top_row: bool = True
) -> tuple[list[tuple[str, float]], list[str]]:
    runs: list[tuple[str, float]] = []
    texts: list[str] = []

    assembled, asm_conf = _assemble_top_row(results, img_h)
    if assembled:
        runs.append((assembled, asm_conf))

    for box, text, prob in results:
        texts.append(text)
        conf = float(prob) * 100.0
        y_center = (box[0][1] + box[2][1]) / 2.0
        if boost_top_row and img_h > 0 and y_center < img_h * 0.55:
            conf = min(100.0, conf * 1.15)
        runs.extend(runs_from_text(text, conf))

    joined = " ".join(t for _, t, _ in results)
    if joined:
        mean_conf = float(np.mean([float(p) for _, _, p in results])) * 100.0
        for digits in spaced_digit_plates(joined):
            runs.append((digits, mean_conf))

    return runs, texts


def read_plate_digits(images: list[np.ndarray]) -> tuple[str, float, str]:
    """Read images and return (best_digit_run, confidence_0_100, full_text)."""
    reader = _get_reader()
    if reader is None:
        return "", 0.0, ""

    runs: list[tuple[str, float]] = []
    texts: list[str] = []
    for img in images:
        img_h = img.shape[0]
        try:
            results = reader.readtext(img, detail=1)
        except Exception:
            continue

        batch_runs, batch_texts = _collect_runs_from_results(results, img_h)
        runs.extend(batch_runs)
        texts.extend(batch_texts)

        # Latin-digit pass helps recover spaced western rows (1 9 7 5 3).
        try:
            latin = reader.readtext(img, detail=1, allowlist="0123456789 ")
        except Exception:
            latin = []
        if latin:
            latin_runs, latin_texts = _collect_runs_from_results(
                latin, img_h, boost_top_row=False
            )
            runs.extend(latin_runs)
            texts.extend(latin_texts)

    if not runs:
        return "", 0.0, " ".join(texts).strip()

    best, conf = pick_best_digits(runs)
    return best, conf, " ".join(texts).strip()


def read_document(img: np.ndarray) -> tuple[str, float]:
    """Read all visible text from a photo/poster (full-page OCR)."""
    reader = _get_reader()
    if reader is None:
        return "", 0.0

    import cv2

    work = img
    h = img.shape[0]
    if h < 1200:
        scale = 1200 / h
        work = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    try:
        results = reader.readtext(work, paragraph=True, detail=0)
    except Exception:
        return "", 0.0

    lines = [str(t).strip() for t in results if str(t).strip()]
    if not lines:
        return "", 0.0

    # detail=0 has no per-line confidence; use a fixed high score when text is found.
    return "\n".join(lines), 85.0


def read_id_card(img: np.ndarray) -> tuple[str, float]:
    """Read an ID card image with line-level grouping (better for labelled fields)."""
    reader = _get_reader()
    if reader is None:
        return "", 0.0

    import cv2

    work = img
    h = img.shape[0]
    if h < 1200:
        scale = 1200 / h
        work = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    try:
        results = reader.readtext(work, paragraph=False, detail=1)
    except Exception:
        return "", 0.0

    if not results:
        return "", 0.0

    scale_y = work.shape[0] / max(h, 1)
    rows: list[tuple[float, float, str, float]] = []
    for box, text, prob in results:
        text = str(text).strip()
        if not text:
            continue
        y_top = min(p[1] for p in box) / scale_y
        x_left = min(p[0] for p in box)
        rows.append((y_top, x_left, text, float(prob)))

    if not rows:
        return "", 0.0

    rows.sort(key=lambda item: (item[0], item[1]))
    lines: list[str] = []
    current: list[str] = []
    current_y = rows[0][0]
    row_gap = max(12.0, h * 0.025)
    for y_top, _x, text, _prob in rows:
        if current and abs(y_top - current_y) > row_gap:
            lines.append(" ".join(current))
            current = []
        current.append(text)
        current_y = y_top
    if current:
        lines.append(" ".join(current))

    conf = float(np.mean([p for _, _, _, p in rows])) * 100.0
    return "\n".join(lines), conf
