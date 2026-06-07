# OCR System — HTTP API Reference
# مرجع واجهة برمجة التطبيقات — نظام OCR

Base URL (local development):

```
http://127.0.0.1:8000
```

Start the server:

```powershell
.\.venv\Scripts\python.exe run.py
```

Interactive Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## Overview | نظرة عامة

| Feature | Endpoint | Description |
|---------|----------|-------------|
| Document OCR | `POST /api/ocr` | Extract Arabic/English text from documents and images |
| Vehicle Recognition (ANPR) | `POST /api/anpr` | License plate recognition (Latin & Arabic-Indic plates) |
| Live ANPR UI | `GET /anpr/live` | Browser page with camera preview, ROI crop, and streaming recognition |
| Live ANPR (WebSocket) | `WS /ws/anpr` | Stream cropped JPEG frames from a live camera for plate recognition |
| Live ANPR (single frame) | `POST /api/anpr/frame` | HTTP alternative: upload one JPEG frame (same pipeline as `/api/anpr`) |
| KYC & Onboarding | `POST /api/kyc` | Iraqi national ID / passport identity field extraction |
| Health | `GET /api/health` | Engine status, installed languages, ANPR component availability |

All upload endpoints accept **multipart/form-data** with a maximum file size of **15 MB** (`POST /api/anpr/frame` uses a **4 MB** cap for live JPEG frames).

---

## Common errors

| HTTP status | When |
|-------------|------|
| `400` | Empty file, invalid/corrupt image, or processing error (`detail` string in JSON body) |
| `413` | File exceeds 15 MB |
| `503` | Tesseract is not installed or not found (set `TESSERACT_CMD` or see [README](../README.md)) |

Error response shape:

```json
{
  "detail": "Empty file uploaded."
}
```

---

## GET /api/health

Returns engine status and which optional ANPR components are active.

### Response fields

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Always `"ok"` when the server is running |
| `version` | string | Application version (e.g. `"1.0.0"`) |
| `tesseract_path` | string \| null | Resolved path to `tesseract.exe` / binary |
| `tessdata_path` | string \| null | Tessdata directory in use |
| `tesseract_version` | string \| null | Tesseract version string |
| `installed_languages` | string[] | Language packs available to Tesseract (e.g. `["eng", "ara"]`) |
| `supported_languages` | object | Map of supported API language codes → display names |
| `anpr_detector` | string | `"yolo"` if YOLO weights are loaded, else `"classic-cv"` |
| `super_resolution` | boolean | Whether EDSR super-resolution model is available |
| `plate_reader` | string | `"easyocr"` if EasyOCR is installed, else `"tesseract"` |
| `gpu` | object | `{ "available": bool, "name": string \| null }` |

### Example response

```json
{
  "status": "ok",
  "version": "1.0.0",
  "tesseract_path": "C:\\Program Files\\Tesseract-OCR\\tesseract.exe",
  "tessdata_path": null,
  "tesseract_version": "5.5.0",
  "installed_languages": ["eng", "ara", "osd"],
  "supported_languages": {
    "eng": "English",
    "ara": "Arabic (العربية)",
    "eng+ara": "English + Arabic"
  },
  "anpr_detector": "yolo",
  "super_resolution": true,
  "plate_reader": "easyocr",
  "gpu": {
    "available": false,
    "name": null
  }
}
```

### curl

```powershell
curl http://127.0.0.1:8000/api/health
```

### Python

```python
import requests

r = requests.get("http://127.0.0.1:8000/api/health")
print(r.json())
```

---

## POST /api/ocr — Document OCR
## استخراج النص من المستندات (عربي / إنجليزي)

General-purpose OCR for scanned documents, photos, posters, and mixed Arabic/English content.

### Request (multipart/form-data)

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `file` | yes | — | Image file (PNG, JPEG, TIFF, BMP, WebP, etc.) |
| `lang` | no | `eng+ara` | Tesseract language code: `eng`, `ara`, or `eng+ara` |
| `psm` | no | `3` | Page Segmentation Mode (Tesseract `--psm`). Use `6` for uniform blocks, `7` for a single text line |
| `preprocess` | no | `true` | Apply OpenCV preprocessing (grayscale, upscale, denoise, binarization, deskew) |

### Response fields

| Field | Type | Description |
|-------|------|-------------|
| `text` | string | Full extracted text |
| `language` | string | Language code used |
| `mean_confidence` | number | Average word confidence (0–100) |
| `word_count` | integer | Number of recognized words |
| `words` | array | Per-word details (see below) |

Each item in `words`:

| Field | Type | Description |
|-------|------|-------------|
| `text` | string | Word or line text |
| `confidence` | number | Confidence 0–100 |
| `box` | `[left, top, width, height]` | Bounding box in pixels |

### Example response

```json
{
  "text": "Hello World\nمرحبا بالعالم",
  "language": "eng+ara",
  "mean_confidence": 87.42,
  "word_count": 4,
  "words": [
    {
      "text": "Hello",
      "confidence": 92.5,
      "box": [120, 45, 80, 22]
    },
    {
      "text": "World",
      "confidence": 89.1,
      "box": [210, 45, 75, 22]
    },
    {
      "text": "مرحبا",
      "confidence": 85.3,
      "box": [120, 90, 60, 24]
    },
    {
      "text": "بالعالم",
      "confidence": 82.8,
      "box": [190, 90, 70, 24]
    }
  ]
}
```

### curl (PowerShell)

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/ocr" `
  -F "file=@C:\path\to\scan.png" `
  -F "lang=eng+ara" `
  -F "psm=3" `
  -F "preprocess=true"
```

Arabic only:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/ocr" -F "file=@arabic.png" -F "lang=ara"
```

### Python

```python
import requests

with open("scan.png", "rb") as f:
    r = requests.post(
        "http://127.0.0.1:8000/api/ocr",
        files={"file": ("scan.png", f, "image/png")},
        data={"lang": "eng+ara", "psm": 3, "preprocess": True},
    )
result = r.json()
print(result["text"])
print(f"Confidence: {result['mean_confidence']}%")
```

---

## POST /api/anpr — Smart City Vehicle Recognition
## التعرف على لوحات المركبات (ANPR)

Automatic Number Plate Recognition for parking, traffic, and smart-city use cases. Supports **Latin digits** and **Arabic/Gulf plates** (Arabic-Indic digits ٠–٩); digits are normalized to Latin in the response.

### Request (multipart/form-data)

| Field | Required | Description |
|-------|----------|-------------|
| `file` | yes | Vehicle or plate image |

No additional form fields. Detection and OCR settings are chosen automatically.

### Pipeline

1. **YOLOv8** plate detection (when model weights are installed)
2. **EDSR super-resolution** on the plate crop (CPU path)
3. **EasyOCR** for digit reading (preferred), with **Tesseract** fallback

If optional models are missing, the service falls back to classic computer-vision region detection + Tesseract. Check `GET /api/health` for `anpr_detector`, `super_resolution`, and `plate_reader`.

### Response fields

| Field | Type | Description |
|-------|------|-------------|
| `best_plate` | string \| null | Highest-ranked plate number (Latin digits) |
| `best_confidence` | number \| null | Confidence for `best_plate` (0–100) |
| `raw_text` | string | Raw OCR text from the best detection pass |
| `candidates` | array | All plate candidates, ranked best-first |

Each item in `candidates`:

| Field | Type | Description |
|-------|------|-------------|
| `plate` | string | Normalized plate number (Latin digits) |
| `text` | string | Raw OCR text for this region |
| `confidence` | number | Confidence 0–100 |
| `box` | `[x, y, width, height]` | Plate bounding box in image pixels |

### Example response

```json
{
  "best_plate": "10346",
  "best_confidence": 91.25,
  "raw_text": "10346",
  "candidates": [
    {
      "plate": "10346",
      "text": "10346",
      "confidence": 91.25,
      "box": [412, 318, 186, 54]
    },
    {
      "plate": "1034",
      "text": "1034",
      "confidence": 62.0,
      "box": [0, 0, 1920, 1080]
    }
  ]
}
```

When no plate is detected, `best_plate` and `best_confidence` are `null` and `candidates` is an empty array.

### curl (PowerShell)

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/anpr" `
  -F "file=@C:\path\to\car.jpg"
```

### Python

```python
import requests

with open("car.jpg", "rb") as f:
    r = requests.post(
        "http://127.0.0.1:8000/api/anpr",
        files={"file": ("car.jpg", f, "image/jpeg")},
    )
result = r.json()
if result["best_plate"]:
    print(f"Plate: {result['best_plate']} ({result['best_confidence']}%)")
else:
    print("No plate detected")
```

---

## Live ANPR — Camera streaming
## بث الكاميرا المباشر للتعرف على اللوحات

Real-time plate recognition from a device camera. The built-in UI (`GET /anpr/live`) captures video, crops a **region of interest (ROI)** on the client, and streams JPEG frames over WebSocket. Integrators can use the same WebSocket protocol or upload single frames via `POST /api/anpr/frame`.

Recognition uses the same ANPR pipeline as `POST /api/anpr` (YOLO detection → super-resolution → EasyOCR/Tesseract). See [POST /api/anpr](#post-apianpr--smart-city-vehicle-recognition) for response field definitions (`best_plate`, `best_confidence`, `raw_text`, `candidates`).

---

## GET /anpr/live — Live camera UI
## واجهة الكاميرا المباشرة

Serves an HTML page with camera preview, draggable ROI overlay, preset crop regions (center / bottom / full frame), automatic capture every **2 seconds**, manual scan button, and live plate display.

| Item | Value |
|------|-------|
| URL | `http://127.0.0.1:8000/anpr/live` |
| Method | `GET` |
| Response | `text/html` |

Open in a browser after starting the server. The page connects to `WS /ws/anpr` automatically when the camera is started.

```powershell
start http://127.0.0.1:8000/anpr/live
```

---

## WebSocket /ws/anpr — Frame streaming
## بث الإطارات عبر WebSocket

Primary endpoint for low-latency live recognition. The client sends **binary JPEG** frames; the server replies with **JSON** status messages.

### Connect

```
ws://127.0.0.1:8000/ws/anpr
```

On HTTPS deployments use `wss://<host>/ws/anpr` (see [Camera access](#camera-access--إذن-الكاميرا) below).

### Throttling

The server processes **one frame at a time** (no queue). If a new binary frame arrives while recognition is still running, the server immediately replies with:

```json
{ "status": "busy" }
```

The frame is **discarded**. Clients should track `busy` responses and avoid sending while `scanning` is in effect, or pace captures (the built-in UI uses a 2 s interval and skips sends while `scanning` is true).

Maximum frame size: **15 MB** (same as other upload endpoints). Oversized frames return `{"status": "error", "detail": "Frame too large (max 15 MB)."}`.

### Client → server

| Message | Format | Description |
|---------|--------|-------------|
| Frame | Binary (`image/jpeg`) | JPEG image bytes — typically a **client-cropped ROI** (see below) |

Recommended client settings (used by `live-anpr.js`):

| Setting | Value |
|---------|-------|
| Max frame width | 1280 px (height scaled proportionally before crop) |
| JPEG quality | `0.85` |
| Capture interval | ~2000 ms (auto); manual scan minimum 1000 ms apart |

### Server → client (JSON)

Every response is a JSON object with a `status` field:

| `status` | Meaning | Other fields |
|----------|---------|--------------|
| `scanning` | Frame accepted; recognition started | — |
| `busy` | Previous frame still processing — new frame dropped | — |
| `result` | Recognition finished | ANPR fields + `processing_ms` |
| `error` | Processing failed | `detail` (string) |

When `status` is `result`, the payload includes the same fields as `POST /api/anpr`:

| Field | Type | Description |
|-------|------|-------------|
| `best_plate` | string \| null | Highest-ranked plate number (Latin digits) |
| `best_confidence` | number \| null | Confidence for `best_plate` (0–100) |
| `raw_text` | string | Raw OCR text from the best detection pass |
| `candidates` | array | All plate candidates, ranked best-first (each with `plate`, `text`, `confidence`, `box`) |
| `processing_ms` | number | Server-side recognition time in milliseconds |

Example `scanning`:

```json
{ "status": "scanning" }
```

Example `result`:

```json
{
  "status": "result",
  "best_plate": "10346",
  "best_confidence": 91.25,
  "raw_text": "10346",
  "candidates": [
    {
      "plate": "10346",
      "text": "10346",
      "confidence": 91.25,
      "box": [412, 318, 186, 54]
    }
  ],
  "processing_ms": 2840
}
```

Example `error`:

```json
{
  "status": "error",
  "detail": "Tesseract is not installed or not found. Install it (see README) or set TESSERACT_CMD, then restart."
}
```

### JavaScript client example

```javascript
const ws = new WebSocket("ws://127.0.0.1:8000/ws/anpr");
ws.binaryType = "arraybuffer";

ws.onopen = () => console.log("connected");
ws.onmessage = (ev) => {
  const data = JSON.parse(ev.data);
  if (data.status === "result") {
    console.log(data.best_plate, data.best_confidence, data.processing_ms + " ms");
  } else if (data.status === "busy") {
    console.log("server busy — frame dropped");
  } else if (data.status === "error") {
    console.error(data.detail);
  }
};

// Send a cropped JPEG ArrayBuffer (e.g. from canvas.toBlob → arrayBuffer)
function sendFrame(jpegArrayBuffer) {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(jpegArrayBuffer);
  }
}
```

---

## POST /api/anpr/frame — Single frame upload
## رفع إطار واحد من الكاميرا

HTTP alternative when WebSockets are unavailable. Accepts one JPEG frame and runs the same recognition as `POST /api/anpr`, with `processing_ms` added to the response.

### Request (multipart/form-data)

| Field | Required | Description |
|-------|----------|-------------|
| `file` | yes | JPEG frame (typically client-cropped ROI) |

Maximum frame size: **4 MB** (stricter than WebSocket to suit mobile uploads).

### Response fields

Same as [POST /api/anpr](#post-apianpr--smart-city-vehicle-recognition), plus:

| Field | Type | Description |
|-------|------|-------------|
| `processing_ms` | number | Server-side recognition time in milliseconds |

### Example response

```json
{
  "best_plate": "10346",
  "best_confidence": 91.25,
  "raw_text": "10346",
  "candidates": [],
  "processing_ms": 2650
}
```

### curl (PowerShell)

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/anpr/frame" `
  -F "file=@C:\path\to\frame.jpg"
```

### Python

```python
import requests

with open("frame.jpg", "rb") as f:
    r = requests.post(
        "http://127.0.0.1:8000/api/anpr/frame",
        files={"file": ("frame.jpg", f, "image/jpeg")},
    )
result = r.json()
print(result.get("best_plate"), result.get("processing_ms"), "ms")
```

---

## Region of interest (ROI) — client-side crop
## منطقة الاهتمام — قصّ الإطار على العميل

The server receives **already-cropped** JPEG images. ROI selection is performed entirely in the browser (or your client):

1. Scale the video frame so width ≤ 1280 px.
2. Crop a normalized rectangle `(x, y, w, h)` where each value is 0–1 relative to the scaled frame.
3. Encode the crop as JPEG and send via WebSocket or `POST /api/anpr/frame`.

The built-in UI (`GET /anpr/live`) provides draggable ROI handles and presets:

| Preset | Normalized `(x, y, w, h)` | Use case |
|--------|---------------------------|----------|
| `center` | `(0.15, 0.35, 0.7, 0.3)` | Plate in middle of frame |
| `bottom` | `(0.1, 0.55, 0.8, 0.4)` | Rear / front bumper plates |
| `full` | `(0, 0, 1, 1)` | Full frame (slower, more false positives) |

Minimum ROI size: **20%** of frame width and height. ROI per camera device is persisted in `localStorage` by the built-in UI.

Bounding boxes in `candidates[].box` are relative to the **cropped image** sent to the server, not the full camera view.

---

## Camera access — إذن الكاميرا

Live capture uses the browser [MediaDevices.getUserMedia()](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia) API.

| Environment | Camera access |
|-------------|---------------|
| `http://localhost` or `http://127.0.0.1` | Allowed (secure context exception) |
| `http://<LAN-IP>` or other HTTP host | **Blocked** — use HTTPS |
| `https://<host>` | Allowed (user must grant permission) |

Typical constraints used by the built-in UI: `{ video: { width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false }`, with optional `deviceId` for multi-camera selection and `facingMode: "environment"` on mobile when no device is selected.

Common errors: `NotAllowedError` (permission denied), `NotFoundError` (no camera), `NotReadableError` (camera in use by another app).

---

## POST /api/kyc — KYC & Onboarding
## استخراج بيانات الهوية — البطاقة الوطنية العراقية

Extracts identity fields from passports, national IDs, and driver licenses. Optimized for the **Iraqi Unified National Card** (البطاقة الوطنية الموحدة) with Arabic/Kurdish bilingual labels and **TD1 MRZ** (3×30) parsing.

Upload the **front** as `file`. Optionally upload the **back** as `file_back`; fields from both sides are merged (higher-quality values win).

### Request (multipart/form-data)

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `file` | yes | — | Front of ID / passport / license image |
| `file_back` | no | — | Back of ID (recommended for Iraqi cards — MRZ and extra fields) |
| `lang` | no | `eng+ara` | OCR language: `eng`, `ara`, or `eng+ara` |

### Response fields

| Field | Type | Description |
|-------|------|-------------|
| `fields` | object | Extracted key-value pairs (see Iraqi field table below) |
| `mrz` | object \| null | Parsed MRZ data (TD1 Iraqi ID or TD3 passport), omitted keys when empty |
| `confidence` | number | Overall confidence score (0–100) |
| `raw_text` | string | Combined OCR text; multiple images separated by `\n---\n` |

### Iraqi ID `fields` keys

| Key | Arabic label (approx.) | Example |
|-----|------------------------|---------|
| `name` | الاسم | `عمار` |
| `father_name` | الأب | `حسين` |
| `grandfather_name` | الجد | `محمد` |
| `surname` | اللقب | `الأسفر` |
| `mother_name` | الأم | `فاطمة` |
| `gender` | الجنس | `ذكر` or `أنثى` |
| `blood_type` | فصيلة الدم | `+O` |
| `date_of_birth` | تاريخ الولادة | `1990/05/15` (YYYY/MM/DD) |
| `date_of_issue` | تاريخ الإصدار | `2020/01/10` |
| `expiry_date` | تاريخ النفاذ | `2030/01/09` |
| `place_of_birth` | محل الولادة | `بغداد` |
| `issuing_authority` | جهة الإصدار | `مديرية الجنسية` |
| `national_id` | الرقم الوطني | 12-digit national ID |
| `serial_number` | الرقم التسلسلي | `AR1234567` |
| `family_number` | الرقم العائلي | Family registry number |
| `document_number` | — | Passport/other document number (English-label fallback) |

### `mrz` object (when detected)

| Field | Description |
|-------|-------------|
| `document_type` | e.g. `ID` |
| `issuing_country` | e.g. `IRQ` |
| `surname` | Latin surname from MRZ |
| `given_names` | Latin given name(s) |
| `document_number` | Document serial (e.g. `AR1234567`) |
| `nationality` | e.g. `IRQ` |
| `date_of_birth` | `YYYY/MM/DD` |
| `sex` | `M` or `F` |
| `expiry_date` | `YYYY/MM/DD` |
| `national_id` | 12-digit ID from MRZ optional field |

Only non-empty MRZ fields are included in the response.

### Example response (Iraqi national ID)

```json
{
  "fields": {
    "name": "عمار",
    "father_name": "حسين",
    "grandfather_name": "محمد",
    "surname": "الأسفر",
    "mother_name": "فاطمة",
    "gender": "ذكر",
    "blood_type": "+O",
    "date_of_birth": "1990/05/15",
    "date_of_issue": "2020/01/10",
    "expiry_date": "2030/01/09",
    "place_of_birth": "بغداد - الكرخ",
    "national_id": "199012345678",
    "serial_number": "AR1234567",
    "family_number": "1234A56B7890123456789"
  },
  "mrz": {
    "document_type": "ID",
    "issuing_country": "IRQ",
    "surname": "Alasfar",
    "given_names": "Ammar",
    "document_number": "AR1234567",
    "nationality": "IRQ",
    "date_of_birth": "1990/05/15",
    "sex": "M",
    "expiry_date": "2030/01/09",
    "national_id": "199012345678"
  },
  "confidence": 78.5,
  "raw_text": "جمهورية العراق\nالاسم: عمار\n...\nIDIRQ123456789012345678901234\n..."
}
```

### curl — front only (PowerShell)

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/kyc" `
  -F "file=@C:\path\to\id_front.jpg" `
  -F "lang=eng+ara"
```

### curl — front + back (recommended for Iraqi ID)

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/kyc" `
  -F "file=@C:\path\to\id_front.jpg" `
  -F "file_back=@C:\path\to\id_back.jpg" `
  -F "lang=eng+ara"
```

### Python

```python
import requests

with open("id_front.jpg", "rb") as front, open("id_back.jpg", "rb") as back:
    r = requests.post(
        "http://127.0.0.1:8000/api/kyc",
        files={
            "file": ("id_front.jpg", front, "image/jpeg"),
            "file_back": ("id_back.jpg", back, "image/jpeg"),
        },
        data={"lang": "eng+ara"},
    )

result = r.json()
print("Fields:", result["fields"])
if result["mrz"]:
    print("MRZ national_id:", result["mrz"].get("national_id"))
print(f"Confidence: {result['confidence']}%")
```

---

## Notes

### Supported languages

| Code | Use case |
|------|----------|
| `eng` | English-only documents |
| `ara` | Arabic-only documents |
| `eng+ara` | Mixed or bilingual content (**default** for OCR and KYC) |

Tesseract must have the corresponding traineddata installed. Run `GET /api/health` and check `installed_languages`.

### Live ANPR tips

- Crop to the plate area on the client (ROI) before sending — smaller images process faster and reduce false detections.
- Pace frames to match server throughput (~2 s interval in the built-in UI); respect `busy` responses instead of queuing frames.
- For mobile or non-WebSocket clients, use `POST /api/anpr/frame` with the same cropped JPEG.
- On remote hosts, serve over **HTTPS** so browsers allow `getUserMedia`.

### ANPR optional models

For best accuracy (small plates in full car photos, Arabic-Indic digits), install the deep-learning stack:

- **YOLOv8** — plate localization (`models/license_plate_yolov8.pt`)
- **EDSR x4** — super-resolution (`models/EDSR_x4.pb`)
- **EasyOCR** — plate digit reader (auto-downloads weights on first use)

See [README — Deep-learning ANPR](../README.md#deep-learning-anpr-optional-recommended-for-car-scene-photos) for setup. Without these, ANPR uses classic CV + Tesseract (works well for close-up Latin plates).

### KYC accuracy tips

- Upload **high-resolution** photos (300 DPI or higher when scanning).
- For Iraqi IDs, send **both front and back** (`file` + `file_back`) so MRZ and labeled fields can be merged.
- **MRZ parsing** (TD1 for Iraqi ID, TD3 for passports) is the most reliable signal when present.
- Label-based field extraction is heuristic; verify critical fields against the physical document.

### PSM quick reference (Document OCR)

| PSM | When to use |
|-----|-------------|
| `3` | Automatic page layout (default) |
| `6` | Single uniform block of text |
| `7` | Single text line (e.g. cropped plate text via general OCR) |
| `11` | Sparse text (used internally for photo-like images) |

---

## Related

- [README](../README.md) — installation, CLI usage, project layout
- [Swagger UI](http://127.0.0.1:8000/docs) — try all endpoints in the browser
- [ReDoc](http://127.0.0.1:8000/redoc) — alternative API documentation view
