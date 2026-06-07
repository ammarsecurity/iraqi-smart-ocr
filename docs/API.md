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
| KYC & Onboarding | `POST /api/kyc` | Iraqi national ID / passport identity field extraction |
| Health | `GET /api/health` | Engine status, installed languages, ANPR component availability |

All upload endpoints accept **multipart/form-data** with a maximum file size of **15 MB**.

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
