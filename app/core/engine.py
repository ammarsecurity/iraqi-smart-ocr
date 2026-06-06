"""Tesseract OCR engine wrapper.

Wraps pytesseract with sensible defaults, preprocessing, word-level confidence
extraction and bounding boxes. Supports Arabic, English, or both at once.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pytesseract
from pytesseract import Output

from .. import config
from . import preprocess


class TesseractNotInstalled(RuntimeError):
    """Raised when the Tesseract binary cannot be located."""


@dataclass
class Word:
    text: str
    confidence: float
    box: tuple[int, int, int, int]  # (left, top, width, height)


@dataclass
class OCRResult:
    text: str
    language: str
    mean_confidence: float
    words: list[Word] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "language": self.language,
            "mean_confidence": round(self.mean_confidence, 2),
            "word_count": len(self.words),
            "words": [
                {"text": w.text, "confidence": round(w.confidence, 2), "box": list(w.box)}
                for w in self.words
            ],
        }


def ensure_available() -> None:
    if config.locate_tesseract() is None:
        raise TesseractNotInstalled(
            "Tesseract binary not found. Install it and/or set the TESSERACT_CMD "
            "environment variable. See the README for installation instructions."
        )


# Page Segmentation Modes tried (in order) when the requested one finds nothing.
# PSM 3 (auto layout) often fails on short/boxed content like plates or single
# blocks, whereas 6 (uniform block) and 11 (sparse text) succeed.
_FALLBACK_PSMS = [6, 11, 4, 7]


def _single_pass(work: np.ndarray, lang: str, psm: int, oem: int) -> OCRResult:
    cfg = f"--oem {oem} --psm {psm}"
    text = pytesseract.image_to_string(work, lang=lang, config=cfg).strip()
    data = pytesseract.image_to_data(work, lang=lang, config=cfg, output_type=Output.DICT)

    words: list[Word] = []
    confidences: list[float] = []
    for i, token in enumerate(data["text"]):
        token = token.strip()
        conf = float(data["conf"][i])
        if not token or conf < 0:
            continue
        words.append(
            Word(
                text=token,
                confidence=conf,
                box=(
                    int(data["left"][i]),
                    int(data["top"][i]),
                    int(data["width"][i]),
                    int(data["height"][i]),
                ),
            )
        )
        confidences.append(conf)

    mean_conf = float(np.mean(confidences)) if confidences else 0.0
    return OCRResult(text=text, language=lang, mean_confidence=mean_conf, words=words)


def _pick_best_result(candidates: list[OCRResult]) -> OCRResult:
    """Choose the best OCR result by word count, confidence, and text length."""
    if not candidates:
        return OCRResult(text="", language="", mean_confidence=0.0, words=[])

    def score(r: OCRResult) -> tuple:
        return (len(r.words), r.mean_confidence, len(r.text))

    return max(candidates, key=score)


def run_ocr(
    image: np.ndarray,
    *,
    lang: str = config.DEFAULT_LANGUAGE,
    psm: int = 3,
    oem: int = 3,
    preprocess_image: bool = True,
    preprocess_mode: str = "otsu",
    auto_fallback: bool = True,
) -> OCRResult:
    """Run OCR on an OpenCV image and return text + word-level details.

    For colorful posters/photos, automatically tries a light pipeline and
    EasyOCR (when installed) in addition to the standard document path.
    """
    ensure_available()

    photo = preprocess.is_photo_like(image)

    # Posters / UI graphics: EasyOCR handles stylized Arabic+English much better.
    if photo:
        try:
            from ..features import easyocr_reader

            if easyocr_reader.is_available():
                text, conf = easyocr_reader.read_document(image)
                if text and len(text) >= 60:
                    lines = [ln for ln in text.splitlines() if ln.strip()]
                    return OCRResult(
                        text=text,
                        language=lang,
                        mean_confidence=conf,
                        words=[
                            Word(text=ln, confidence=conf, box=(0, 0, 0, 0))
                            for ln in lines
                        ],
                    )
        except Exception:
            pass

    mode = "photo" if (preprocess_image and photo) else preprocess_mode
    candidates: list[OCRResult] = []

    if preprocess_image:
        work = preprocess.prepare_for_ocr(image, mode=mode)
    else:
        work = preprocess.upscale(image, min_height=1200)

    psm_use = 11 if photo else psm
    candidates.append(_single_pass(work, lang, psm_use, oem))

    if auto_fallback and not candidates[-1].words:
        for alt in _FALLBACK_PSMS:
            if alt == psm_use:
                continue
            candidates.append(_single_pass(work, lang, alt, oem))
            if candidates[-1].words:
                break

    # Posters: also try raw color upscale (no binarization).
    if photo:
        color = preprocess.upscale(image, min_height=1200)
        candidates.append(_single_pass(color, lang, 11, oem))

    return _pick_best_result(candidates)


def run_ocr_bytes(data: bytes, **kwargs) -> OCRResult:
    """Convenience wrapper that decodes raw bytes first."""
    return run_ocr(preprocess.to_cv_image(data), **kwargs)
