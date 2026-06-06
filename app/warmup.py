"""Preload heavy ANPR models at server startup so the first request is fast."""

from __future__ import annotations

import logging

logger = logging.getLogger("ocr.warmup")


def warmup_anpr() -> None:
    """Load YOLO, EasyOCR, and super-resolution models into memory."""
    try:
        import torch

        if torch.cuda.is_available():
            logger.info("GPU: %s", torch.cuda.get_device_name(0))
    except Exception:
        pass

    from .features import easyocr_reader, plate_detector
    from .core import superres

    if plate_detector.is_available():
        plate_detector._get_model()
        logger.info("YOLO plate detector loaded")

    if easyocr_reader.is_available():
        easyocr_reader._get_reader()
        logger.info("EasyOCR reader loaded")

    if superres.is_available():
        superres._get_sr()
        logger.info("Super-resolution model loaded")
