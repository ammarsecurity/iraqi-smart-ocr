"""FastAPI application exposing OCR, ANPR and KYC endpoints plus a web UI."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from . import __version__, config
from .core import engine, superres
from .features import anpr, easyocr_reader, kyc, plate_detector
from .warmup import warmup_anpr

logger = logging.getLogger("ocr")

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Preloading ANPR models (YOLO + EasyOCR + SR)…")
    warmup_anpr()
    logger.info("ANPR models ready.")
    yield


app = FastAPI(title="OCR System", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

MAX_BYTES = 15 * 1024 * 1024  # 15 MB upload cap


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 15 MB).")
    return data


def _guard_tesseract() -> None:
    if config.locate_tesseract() is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Tesseract is not installed or not found. Install it (see README) "
                "or set the TESSERACT_CMD environment variable, then restart."
            ),
        )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": __version__,
        "tesseract_path": config.TESSERACT_PATH,
        "tessdata_path": config.TESSDATA_PATH,
        "tesseract_version": config.tesseract_version(),
        "installed_languages": config.available_languages(),
        "supported_languages": config.SUPPORTED_LANGUAGES,
        "anpr_detector": "yolo" if plate_detector.is_available() else "classic-cv",
        "super_resolution": superres.is_available(),
        "plate_reader": "easyocr" if easyocr_reader.is_available() else "tesseract",
        "gpu": _gpu_status(),
    }


def _gpu_status() -> dict:
    try:
        import torch

        return {
            "available": torch.cuda.is_available(),
            "name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        }
    except Exception:
        return {"available": False, "name": None}


@app.post("/api/ocr")
async def api_ocr(
    file: UploadFile = File(...),
    lang: str = Form(config.DEFAULT_LANGUAGE),
    psm: int = Form(3),
    preprocess: bool = Form(True),
):
    _guard_tesseract()
    data = await _read_upload(file)
    try:
        result = engine.run_ocr_bytes(
            data, lang=lang, psm=psm, preprocess_image=preprocess
        )
    except engine.TesseractNotInstalled as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result.to_dict())


@app.post("/api/anpr")
async def api_anpr(file: UploadFile = File(...)):
    _guard_tesseract()
    data = await _read_upload(file)
    try:
        result = anpr.recognize_plate(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result.to_dict())


@app.post("/api/kyc")
async def api_kyc(
    file: UploadFile = File(...),
    file_back: UploadFile | None = File(default=None),
    lang: str = Form(config.DEFAULT_LANGUAGE),
):
    _guard_tesseract()
    data = await _read_upload(file)
    extras: list[bytes] = []
    if file_back is not None and file_back.filename:
        extras.append(await _read_upload(file_back))
    try:
        result = kyc.extract_identity(data, lang=lang, extra_images=extras)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result.to_dict())
