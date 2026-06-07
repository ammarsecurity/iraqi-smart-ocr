"""Smart City Vehicle Recognition (ANPR).

Open-source Automatic Number Plate Recognition. Supports both **Latin** plates
and **Arabic / Gulf plates** (Arabic-Indic digits ٠-٩ and Arabic letters), e.g.
Iraqi / Saudi / Kuwaiti plates that carry both scripts and multiple lines.

Strategy: OCR the whole frame (plates that fill the image) with the robust
multi-line engine, and also OCR detected plate-shaped regions (plates inside a
larger scene). The plate *number* is the best plate-like digit run (typically
4–8 digits), with Arabic-Indic digits normalized to Latin.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import pytesseract

from ..core import engine, preprocess, superres
from . import easyocr_reader, plate_detector
from .plate_digits import pick_best_digits, runs_from_text, score_plate_digits

# ASCII digit whitelist (safe to pass on the Windows command line).
_LATIN_DIGITS = "0123456789"


@dataclass
class PlateCandidate:
    plate: str         # the detected plate number (Latin digits)
    text: str          # raw OCR text for this region
    confidence: float
    box: tuple[int, int, int, int]


@dataclass
class ANPRResult:
    plates: list[PlateCandidate]
    raw_text: str = ""

    @property
    def best(self) -> PlateCandidate | None:
        return self.plates[0] if self.plates else None

    def to_dict(self) -> dict:
        return {
            "best_plate": self.best.plate if self.best else None,
            "best_confidence": round(self.best.confidence, 2) if self.best else None,
            "raw_text": self.raw_text.strip(),
            "candidates": [
                {
                    "plate": p.plate,
                    "text": p.text.strip(),
                    "confidence": round(p.confidence, 2),
                    "box": list(p.box),
                }
                for p in self.plates
            ],
        }


def _find_plate_regions(img: np.ndarray, max_regions: int = 8) -> list[tuple[int, int, int, int]]:
    """Find rectangular, plate-shaped contours using edge + morphology."""
    gray = preprocess.grayscale(img)
    gray = cv2.bilateralFilter(gray, 11, 17, 17)
    edges = cv2.Canny(gray, 30, 200)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 5))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    regions: list[tuple[int, int, int, int]] = []
    img_area = img.shape[0] * img.shape[1]
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w == 0 or h == 0:
            continue
        aspect = w / float(h)
        area = w * h
        if 1.2 <= aspect <= 7.0 and 0.004 * img_area <= area <= 0.6 * img_area:
            regions.append((x, y, w, h))
        if len(regions) >= max_regions:
            break
    return regions


def _extract_plate(text: str, conf: float, box: tuple[int, int, int, int]) -> PlateCandidate | None:
    """Pull the best plate-like digit run out of OCR text."""
    runs = runs_from_text(text, conf)
    plate, plate_conf = pick_best_digits(runs)
    if not plate:
        return None
    return PlateCandidate(plate=plate, text=text, confidence=plate_conf, box=box)


def _number_line_crop(crop: np.ndarray) -> np.ndarray:
    """Top portion of a plate crop where the main digit row usually sits."""
    h = crop.shape[0]
    return crop[: max(1, int(h * 0.55)), :]


def _enhance_plate(crop: np.ndarray) -> np.ndarray:
    """Super-resolve (CPU only) + grayscale + upscale + CLAHE for a plate crop."""
    # EDSR super-res runs on CPU and costs ~10s per call. With a GPU for EasyOCR,
    # bicubic upscale is fast enough and accuracy stays good.
    if not _gpu_available():
        crop = superres.upscale(crop, max_height=160)
    gray = preprocess.grayscale(crop)
    gray = preprocess.upscale(gray, min_height=240)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _gpu_available() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False


def _digit_pass(image: np.ndarray, lang: str, whitelist: str | None, psm: int) -> tuple[str, float]:
    """OCR a plate crop; returns the best plate-like digit run + confidence."""
    cfg = f"--oem 3 --psm {psm}"
    if whitelist:
        cfg += f" -c tessedit_char_whitelist={whitelist}"
    try:
        data = pytesseract.image_to_data(
            image, lang=lang, config=cfg, output_type=pytesseract.Output.DICT
        )
    except Exception:
        return "", 0.0

    runs: list[tuple[str, float]] = []
    confs: list[float] = []
    for i, tok in enumerate(data["text"]):
        tok = tok.strip()
        conf = float(data["conf"][i])
        if not tok or conf < 0:
            continue
        confs.append(conf)
        runs.extend(runs_from_text(tok, conf))

    if confs:
        mean_conf = float(np.mean(confs))
        joined = " ".join(t.strip() for t in data["text"] if t.strip())
        runs.extend(runs_from_text(joined, mean_conf))

    return pick_best_digits(runs)


def _is_live_roi_crop(img: np.ndarray, *, user_cropped: bool = False) -> bool:
    """True for small live-camera frames or wide plate strips — not full scene photos."""
    if user_cropped:
        return False
    h, w = img.shape[:2]
    if max(h, w) <= 720:
        return True
    if h * w <= 350_000:
        return True
    if h > 0 and w / float(h) >= 2.8:
        return True
    return False


def _edge_pad_crop(crop: np.ndarray, left_frac: float = 0.03) -> np.ndarray:
    """Replicate a slim left border so leading plate digits are not clipped at OCR edges."""
    pw = max(3, int(crop.shape[1] * left_frac))
    return cv2.copyMakeBorder(crop, 0, 0, pw, 0, cv2.BORDER_REPLICATE)


def _expand_narrow_box(
    img: np.ndarray, box: tuple[int, int, int, int], *, user_cropped: bool = False
) -> tuple[tuple[int, int, int, int], bool]:
    """Widen partial YOLO boxes that only cover part of the digit row (live ROI only)."""
    if not _is_live_roi_crop(img, user_cropped=user_cropped):
        return box, False
    img_h, img_w = img.shape[:2]
    x, y, w, h = box
    if w >= img_w * 0.45:
        return box, False
    pad_y = max(int(h * 0.6), 4)
    y0 = max(0, y - pad_y)
    y1 = min(img_h, y + h + pad_y)
    return (0, y0, img_w, y1 - y0), True


def _ocr_on_crops(
    crops: list[np.ndarray],
) -> tuple[list[tuple[str, float]], str]:
    """Run EasyOCR plate-digit reads on one or more crops; return runs + raw text."""
    all_runs: list[tuple[str, float]] = []
    raw = ""
    if not easyocr_reader.is_available():
        return all_runs, raw

    for crop in crops:
        if crop.size == 0:
            continue
        # Edge padding recovers leading digits EasyOCR drops at tight crop boundaries.
        variants = [crop]
        padded = _edge_pad_crop(crop)
        if padded.shape != crop.shape:
            variants.append(padded)
        for variant in variants:
            num_crop = _number_line_crop(variant)
            for work in (num_crop, variant):
                enhanced = _enhance_plate(work)
                eo_digits, eo_conf, eo_text = easyocr_reader.read_plate_digits([enhanced])
                if eo_digits:
                    all_runs.append((eo_digits, eo_conf))
                if eo_text:
                    raw = eo_text
    return all_runs, raw


def _ocr_plate_crop(
    img: np.ndarray,
    box: tuple[int, int, int, int],
    pad: float = 0.15,
    *,
    user_cropped: bool = False,
) -> PlateCandidate | None:
    """Crop a detected plate box, enhance it, and read the plate number."""
    box, was_narrow = _expand_narrow_box(img, box, user_cropped=user_cropped)
    x, y, w, h = box
    px, py = int(w * pad), int(h * pad)
    x0, y0 = max(0, x - px), max(0, y - py)
    x1, y1 = min(img.shape[1], x + w + px), min(img.shape[0], y + h + py)
    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        return None

    fallback_crops = [crop]
    if _is_live_roi_crop(img, user_cropped=user_cropped) and (was_narrow or w < img.shape[1] * 0.75):
        fallback_crops.append(img)

    all_runs, raw = _ocr_on_crops(fallback_crops)
    best_digits, best_conf = pick_best_digits(all_runs)

    num_crop = _number_line_crop(crop)
    enhanced = _enhance_plate(num_crop)

    # Tesseract — only when EasyOCR failed (2 passes, not 18).
    if len(best_digits) < 3:
        for lang, psm in (("ara", 7), ("eng", 7)):
            digits, conf = _digit_pass(enhanced, lang, _LATIN_DIGITS if lang == "eng" else None, psm)
            if digits:
                all_runs.append((digits, conf))
        best_digits, best_conf = pick_best_digits(all_runs)

    if not raw:
        raw = best_digits

    if len(best_digits) < 3:
        return None
    return PlateCandidate(plate=best_digits, text=raw, confidence=best_conf, box=box)


def recognize_plate(data: bytes, *, user_cropped: bool = False) -> ANPRResult:
    """Detect and read license plates (Latin or Arabic) from image bytes."""
    engine.ensure_available()
    img = preprocess.to_cv_image(data)

    candidates: list[PlateCandidate] = []
    raw_text = ""
    detections: list = []

    # Static upload with client-side ROI: the whole frame is already the plate strip.
    if user_cropped:
        full_box = (0, 0, img.shape[1], img.shape[0])
        cand = _ocr_plate_crop(img, full_box, user_cropped=True)
        if cand:
            candidates.append(cand)
            raw_text = cand.text
        if not candidates:
            whole = engine.run_ocr(img, lang="eng+ara", psm=7)
            raw_text = whole.text
            cand = _extract_plate(
                whole.text, whole.mean_confidence, full_box
            )
            if cand:
                candidates.append(cand)
    else:
        # 1) Deep-learning detector (YOLO) — best for plates inside a full scene.
        detections = plate_detector.detect_plates(img, conf=0.25)
        for box, _det_conf in detections[:3]:
            cand = _ocr_plate_crop(img, box)
            if cand:
                candidates.append(cand)
                raw_text = cand.text
                # Partial reads (e.g. 9753) are common on tight YOLO boxes — keep trying.
                if len(cand.plate) >= 5:
                    break

        # Retry on the full frame when YOLO only yielded a short partial read (live ROI).
        if (
            _is_live_roi_crop(img)
            and candidates
            and all(len(c.plate) < 5 for c in candidates)
        ):
            full_box = (0, 0, img.shape[1], img.shape[0])
            full_cand = _ocr_plate_crop(img, full_box)
            if full_cand:
                candidates.append(full_cand)
                if not raw_text:
                    raw_text = full_cand.text

    # Full-frame fallback only when YOLO found no plate at all.
    if not user_cropped and not candidates and not detections:
        whole = engine.run_ocr(img, lang="eng+ara", psm=6)
        raw_text = whole.text
        cand = _extract_plate(
            whole.text, whole.mean_confidence, (0, 0, img.shape[1], img.shape[0])
        )
        if cand:
            candidates.append(cand)

        for box in _find_plate_regions(img)[:2]:
            x, y, w, h = box
            crop = img[y : y + h, x : x + w]
            try:
                res = engine.run_ocr(crop, lang="eng+ara", psm=7)
            except Exception:
                continue
            cand = _extract_plate(res.text, res.mean_confidence, box)
            if cand:
                candidates.append(cand)
                break

    # De-duplicate by plate number; keep the highest-confidence reading.
    best_by_plate: dict[str, PlateCandidate] = {}
    for c in candidates:
        if c.plate not in best_by_plate or c.confidence > best_by_plate[c.plate].confidence:
            best_by_plate[c.plate] = c

    # Rank by plate-likeness score, then confidence (not raw digit count).
    plates = sorted(
        best_by_plate.values(),
        key=lambda p: (score_plate_digits(p.plate, p.confidence), p.confidence),
        reverse=True,
    )
    return ANPRResult(plates=plates, raw_text=raw_text)
