"""Neural image super-resolution for tiny plate crops.

Small license plates inside a scene end up as ~40px-wide crops that ordinary
bicubic upscaling cannot sharpen enough for OCR. This module runs a learned
super-resolution network (EDSR x4 via OpenCV's ``dnn_superres``) to reconstruct
detail before OCR.

Optional: if the model file or the contrib module is unavailable, ``upscale``
returns the input unchanged and ``is_available`` reports False.
"""

from __future__ import annotations

import threading
from pathlib import Path

import cv2
import numpy as np

MODEL_PATH = Path(__file__).resolve().parent.parent.parent / "models" / "EDSR_x4.pb"
_MODEL_NAME = "edsr"
_SCALE = 4

# Guard rails: SR is expensive, so only apply it to genuinely small crops, and
# never blow a crop up past a sane size.
_MAX_INPUT_PIXELS = 250_000   # ~500x500; bigger crops don't need SR
_MIN_DIM_FOR_SR = 8

_sr = None
_lock = threading.Lock()
_failed = False


def is_available() -> bool:
    if not MODEL_PATH.exists():
        return False
    try:
        from cv2 import dnn_superres  # noqa: F401
    except Exception:
        return False
    return True


def _get_sr():
    global _sr, _failed
    if _sr is not None or _failed:
        return _sr
    with _lock:
        if _sr is None and not _failed:
            try:
                from cv2 import dnn_superres

                sr = dnn_superres.DnnSuperResImpl_create()
                sr.readModel(str(MODEL_PATH))
                sr.setModel(_MODEL_NAME, _SCALE)
                _sr = sr
            except Exception:
                _failed = True
                _sr = None
    return _sr


def upscale(img: np.ndarray, *, max_height: int = 220) -> np.ndarray:
    """Super-resolve ``img`` (BGR or gray) if it is small. Returns BGR/gray.

    Skips work (returns the input) when SR is unavailable, the image is already
    large enough, or anything goes wrong.
    """
    if img is None or img.size == 0:
        return img
    h, w = img.shape[:2]
    if h >= max_height or h < _MIN_DIM_FOR_SR or w < _MIN_DIM_FOR_SR:
        return img
    if h * w > _MAX_INPUT_PIXELS:
        return img
    if not MODEL_PATH.exists():
        return img

    sr = _get_sr()
    if sr is None:
        return img

    was_gray = img.ndim == 2
    bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if was_gray else img
    try:
        out = sr.upsample(bgr)
    except Exception:
        return img
    if was_gray:
        return cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    return out
