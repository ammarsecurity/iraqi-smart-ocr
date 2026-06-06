"""Image preprocessing pipeline built on OpenCV.

Good preprocessing is the single biggest lever on Tesseract accuracy. These
helpers cover the steps recommended in the Tesseract docs: grayscale, upscale,
denoise, binarize (Otsu / adaptive) and deskew.
"""

from __future__ import annotations

import cv2
import numpy as np


def to_cv_image(data: bytes) -> np.ndarray:
    """Decode raw image bytes into an OpenCV BGR ndarray (EXIF orientation applied)."""
    try:
        import io

        from PIL import Image, ImageOps

        pil = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        rgb = np.array(pil.convert("RGB"))
        img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        if img is not None and img.size:
            return img
    except Exception:
        pass

    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image. Unsupported or corrupt file.")
    return img


def rotate_image(img: np.ndarray, degrees: int) -> np.ndarray:
    """Rotate by 0, 90, 180, or 270 degrees clockwise."""
    if degrees == 0:
        return img
    if degrees == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if degrees == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if degrees == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    raise ValueError(f"Unsupported rotation: {degrees}")


def osd_rotation(img: np.ndarray) -> int | None:
    """Return clockwise correction degrees from Tesseract OSD, or None."""
    try:
        import pytesseract

        gray = grayscale(img)
        gray = upscale(gray, min_height=800)
        osd = pytesseract.image_to_osd(gray, output_type=pytesseract.Output.DICT)
        rotate = int(osd.get("rotate", 0))
        return rotate if rotate in (0, 90, 180, 270) else None
    except Exception:
        return None


def grayscale(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def upscale(img: np.ndarray, min_height: int = 1000) -> np.ndarray:
    """Upscale small images — Tesseract performs poorly below ~300 DPI."""
    h = img.shape[0]
    if h >= min_height:
        return img
    scale = min_height / float(h)
    return cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def denoise(gray: np.ndarray) -> np.ndarray:
    return cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)


def binarize_otsu(gray: np.ndarray) -> np.ndarray:
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh


def binarize_adaptive(gray: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
    )


# Only correct genuinely small skews. Larger estimates almost always mean the
# minAreaRect locked onto a border/box rather than the text baseline, so trying
# to "fix" them rotates upright text sideways and destroys OCR.
_MAX_DESKEW_DEG = 15.0


def deskew(gray: np.ndarray) -> np.ndarray:
    """Estimate and correct small page rotation using the text mask.

    OpenCV's ``minAreaRect`` reports the angle in the ``[0, 90]`` range (since
    4.5), so we normalize it into ``(-45, 45]`` before deciding whether to
    rotate. Angles outside a small band are treated as misdetections and skipped.
    """
    inverted = cv2.bitwise_not(gray)
    coords = np.column_stack(np.where(inverted > 0))
    if coords.shape[0] < 10:
        return gray

    angle = cv2.minAreaRect(coords.astype(np.float32))[-1]
    if angle > 45:
        angle -= 90  # normalize to a small signed rotation

    if abs(angle) < 0.5 or abs(angle) > _MAX_DESKEW_DEG:
        return gray

    h, w = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        gray, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def prepare_for_photo_ocr(img: np.ndarray) -> np.ndarray:
    """Light pipeline for posters/photos — no binarization (preserves colored text)."""
    gray = grayscale(img)
    gray = upscale(gray, min_height=1200)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def is_photo_like(img: np.ndarray) -> bool:
    """True for colorful images (posters, UI screenshots, marketing graphics)."""
    if img.ndim != 3:
        return False
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    sat = float(hsv[:, :, 1].mean())
    val_std = float(hsv[:, :, 2].std())
    return sat > 35 and val_std > 30


def prepare_for_ocr(
    img: np.ndarray,
    *,
    do_denoise: bool = True,
    do_deskew: bool = True,
    mode: str = "otsu",
) -> np.ndarray:
    """Full document pipeline returning a clean binary image for Tesseract."""
    if mode == "photo":
        return prepare_for_photo_ocr(img)

    gray = grayscale(img)
    gray = upscale(gray)
    if do_denoise:
        gray = denoise(gray)
    if mode == "adaptive":
        binary = binarize_adaptive(gray)
    else:
        binary = binarize_otsu(gray)
    if do_deskew:
        binary = deskew(binary)
    return binary
