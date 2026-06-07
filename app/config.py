"""Configuration and Tesseract discovery.

On Windows, Tesseract is not on PATH by default after the UB Mannheim install,
so we proactively probe the common install locations. On macOS/Linux we rely on
PATH (e.g. `brew install tesseract`).
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

import pytesseract

logger = logging.getLogger("ocr")


def _load_dotenv() -> None:
    """Load key=value pairs from a project-root .env file if present."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

# Shared secret for public deployments. Set OCR_API_KEY (preferred) or API_KEY.
# When unset, API key checks are disabled (local development only).
API_KEY = (os.environ.get("OCR_API_KEY") or os.environ.get("API_KEY") or "").strip() or None
if API_KEY:
    logger.info("API key authentication is enabled.")
else:
    logger.warning(
        "OCR_API_KEY is not set — API endpoints are open. "
        "Set OCR_API_KEY before exposing this server publicly."
    )

# Project-local tessdata. If present, we point Tesseract here so the app uses
# our bundled language models (e.g. a custom/better ara.traineddata) instead of
# the system ones. Falls back to the system tessdata when this folder is absent.
_LOCAL_TESSDATA = Path(__file__).resolve().parent.parent / "tessdata"


def configure_tessdata() -> str | None:
    """Point TESSDATA_PREFIX at the project-local tessdata folder if it exists."""
    if _LOCAL_TESSDATA.is_dir() and any(_LOCAL_TESSDATA.glob("*.traineddata")):
        os.environ["TESSDATA_PREFIX"] = str(_LOCAL_TESSDATA)
        return str(_LOCAL_TESSDATA)
    return os.environ.get("TESSDATA_PREFIX")

# Languages we ship support for out of the box.
SUPPORTED_LANGUAGES = {
    "eng": "English",
    "ara": "Arabic",
    "eng+ara": "English + Arabic",
}
DEFAULT_LANGUAGE = "eng+ara"

# Common Windows install directories for the UB Mannheim build.
_WINDOWS_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
]


def locate_tesseract() -> str | None:
    """Return the path to the tesseract binary, or None if not found.

    Resolution order:
      1. TESSERACT_CMD environment variable (explicit override).
      2. A binary already on PATH.
      3. Known Windows install locations.
    """
    override = os.environ.get("TESSERACT_CMD")
    if override and Path(override).exists():
        return override

    on_path = shutil.which("tesseract")
    if on_path:
        return on_path

    for candidate in _WINDOWS_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate

    return None


def configure_tesseract() -> str | None:
    """Point pytesseract at the discovered binary. Returns the path used."""
    cmd = locate_tesseract()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    return cmd


def available_languages() -> list[str]:
    """Languages actually installed in the local tessdata, best effort."""
    try:
        return sorted(pytesseract.get_languages(config=""))
    except Exception:
        return []


def tesseract_version() -> str | None:
    try:
        return str(pytesseract.get_tesseract_version())
    except Exception:
        return None


# Configure on import so other modules can use it immediately.
TESSERACT_PATH = configure_tesseract()
TESSDATA_PATH = configure_tessdata()
