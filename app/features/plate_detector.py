"""Deep-learning license-plate detector (YOLOv8 via Ultralytics)."""

from __future__ import annotations

import threading
from pathlib import Path

import cv2
import numpy as np

MODEL_PATH = Path(__file__).resolve().parent.parent.parent / "models" / "license_plate_yolov8.pt"

_model = None
_device: str | int = "cpu"
_load_lock = threading.Lock()
_load_failed = False


def _resolve_device() -> str | int:
    try:
        import torch

        if torch.cuda.is_available():
            return 0
    except Exception:
        pass
    return "cpu"


def is_available() -> bool:
    if not MODEL_PATH.exists():
        return False
    try:
        import ultralytics  # noqa: F401
    except Exception:
        return False
    return True


def _get_model():
    """Lazily load the YOLO model once (thread-safe)."""
    global _model, _device, _load_failed
    if _model is not None or _load_failed:
        return _model
    with _load_lock:
        if _model is None and not _load_failed:
            try:
                from ultralytics import YOLO

                _device = _resolve_device()
                _model = YOLO(str(MODEL_PATH))
            except Exception:
                _load_failed = True
                _model = None
    return _model


def detect_plates(
    img_bgr: np.ndarray,
    *,
    conf: float = 0.25,
    max_plates: int = 3,
) -> list[tuple[tuple[int, int, int, int], float]]:
    """Detect plates. Returns a list of ((x, y, w, h), confidence), best first."""
    if not MODEL_PATH.exists():
        return []
    model = _get_model()
    if model is None:
        return []

    # Downscale very large photos — YOLO only needs ~640 px; saves GPU time.
    h, w = img_bgr.shape[:2]
    work = img_bgr
    scale = 1.0
    max_side = max(h, w)
    if max_side > 1280:
        scale = 1280 / max_side
        work = cv2.resize(img_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    try:
        results = model.predict(work, conf=conf, verbose=False, device=_device)
    except Exception:
        return []

    h_img, w_img = img_bgr.shape[:2]
    inv = 1.0 / scale
    boxes: list[tuple[tuple[int, int, int, int], float]] = []
    for r in results:
        for b in r.boxes:
            x1, y1, x2, y2 = (int(v * inv) for v in b.xyxy[0].tolist())
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w_img, x2), min(h_img, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            boxes.append(((x1, y1, x2 - x1, y2 - y1), float(b.conf[0])))

    boxes.sort(key=lambda item: item[1], reverse=True)
    return boxes[:max_plates]
