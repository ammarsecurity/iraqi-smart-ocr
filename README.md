# OCR System — Arabic + English (Tesseract)

A complete, **offline** OCR system built on [Tesseract](https://tesseractocr.org).
It supports **Arabic (العربية)** and **English** out of the box and ships two
extra features:

- 🚗 **Smart City Vehicle Recognition (ANPR)** — open-source Automatic Number
  Plate Recognition for parking and traffic systems.
- 🪪 **KYC & Onboarding** — extract names and IDs from passports, national IDs
  and driver licenses, with **MRZ** (machine-readable zone) parsing.

Everything runs locally — no API keys, no cloud, full privacy.

---

## 1. Install Tesseract (the engine)

This project wraps the Tesseract binary, so you need it installed first.
Pick your OS — these are the official instructions from
<https://tesseractocr.org/#install>.

### Windows (your machine)
Tesseract can't be compiled easily on Windows, so use the official pre-built
installer from the **UB Mannheim** project:

1. Download & run the installer from
   <https://github.com/UB-Mannheim/tesseract/wiki>.
2. **During setup, tick "Additional language data" and select Arabic (`ara`)**
   so Arabic is installed.
3. Default install path is `C:\Program Files\Tesseract-OCR`.
   This project auto-detects that path, so you do **not** have to edit `PATH`.
   (If you installed elsewhere, set the `TESSERACT_CMD` env var to the full
   path of `tesseract.exe`.)

> On this machine Tesseract **5.5.0** is already installed at
> `C:\Program Files\Tesseract-OCR` with both `eng` and `ara` language data. ✅

### macOS
```bash
brew install tesseract        # core engine
brew install tesseract-lang   # all language packs (includes Arabic)
tesseract --version
```

### Ubuntu / Debian
```bash
sudo apt install tesseract-ocr
sudo apt install tesseract-ocr-ara   # Arabic language data
tesseract --version
```

---

## 2. Install the Python app

Requires Python 3.10+ (tested on 3.14).

### Windows (PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### macOS / Linux
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

---

## 3. Run

### Web app (recommended)
```powershell
.\.venv\Scripts\python.exe run.py
```
Open <http://127.0.0.1:8000>. You get three tabs: **Document OCR**,
**Vehicle Plate (ANPR)** and **KYC & Onboarding**, each with drag-and-drop
upload and a language selector (English / Arabic / both).

### Command line
```powershell
# Check the engine + installed languages
.\.venv\Scripts\python.exe cli.py info

# OCR a document (Arabic + English)
.\.venv\Scripts\python.exe cli.py ocr scan.png --lang eng+ara -o out.txt

# Arabic only
.\.venv\Scripts\python.exe cli.py ocr arabic.png --lang ara

# Read a vehicle plate
.\.venv\Scripts\python.exe cli.py anpr car.jpg

# Extract identity from a passport / ID
.\.venv\Scripts\python.exe cli.py kyc passport.jpg
```

---

## 4. HTTP API

| Method | Endpoint      | Purpose                                  |
|--------|---------------|------------------------------------------|
| GET    | `/api/health` | Engine status, version, installed langs  |
| POST   | `/api/ocr`    | General OCR — `file`, `lang`, `psm`, `preprocess` |
| POST   | `/api/anpr`   | License plate recognition — `file`       |
| POST   | `/api/kyc`    | ID/passport field extraction — `file`, `lang` |

Example:
```bash
curl -F "file=@scan.png" -F "lang=eng+ara" http://127.0.0.1:8000/api/ocr
```

Interactive API docs (Swagger) are auto-generated at
<http://127.0.0.1:8000/docs>.

---

## 5. Project layout

```
ocr/
├── app/
│   ├── config.py          # Tesseract discovery (auto-finds Windows install)
│   ├── main.py            # FastAPI app + endpoints
│   ├── core/
│   │   ├── preprocess.py  # OpenCV: grayscale, upscale, denoise, binarize, deskew
│   │   └── engine.py      # Tesseract wrapper (text + word confidence + boxes)
│   ├── features/
│   │   ├── anpr.py        # Smart City Vehicle Recognition (plate detection + OCR)
│   │   └── kyc.py         # KYC: labelled-field extraction + ICAO 9303 MRZ parsing
│   └── web/               # HTML/CSS/JS single-page UI (RTL-aware for Arabic)
├── cli.py                 # Command-line interface
├── run.py                 # Web server launcher
└── requirements.txt
```

---

## 6. Tips for best accuracy

Tesseract accuracy depends heavily on image quality. This app already applies
preprocessing (grayscale, upscaling, denoise, Otsu binarization, deskew), but:

- Use **300 DPI or higher**, lossless formats (PNG/TIFF) when possible.
- For a single line (e.g. a cropped plate) use **PSM 7**; for a uniform block
  use **PSM 6**.
- For mixed documents, use `eng+ara`.

## Deep-learning ANPR (optional, recommended for car-scene photos)

By default, ANPR uses classic computer-vision localization + Tesseract, which
works on **close-up** plates (plate fills the frame, e.g. reads `10346`). For
**small plates inside a full car photo** and for **Arabic-Indic plate digits**,
enable the deep-learning stack. It runs a 3-stage pipeline:

```
YOLOv8 (locate plate)  ->  EDSR x4 (super-resolve the crop)  ->  EasyOCR (read)
```

- **YOLOv8** finds the plate even when it's tiny inside a scene.
- **EDSR super-resolution** sharpens a ~40 px plate crop into a legible image.
- **EasyOCR** (deep CRNN) reads Arabic-Indic numerals far better than Tesseract,
  whose Arabic model is trained on document text, not plate fonts.

Setup:

```powershell
# 1. Install the extras (heavy: pulls in PyTorch). Note this uses the OpenCV
#    contrib build, which replaces opencv-python-headless from the base reqs.
.\.venv\Scripts\python.exe -m pip uninstall -y opencv-python opencv-python-headless
.\.venv\Scripts\python.exe -m pip install -r requirements-anpr.txt

# 2. Download the model weights into models/
mkdir models
Invoke-WebRequest -Uri "https://huggingface.co/Koushim/yolov8-license-plate-detection/resolve/main/best.pt" -OutFile "models\license_plate_yolov8.pt"
Invoke-WebRequest -Uri "https://github.com/Saafke/EDSR_Tensorflow/raw/master/models/EDSR_x4.pb" -OutFile "models\EDSR_x4.pb"
```

EasyOCR downloads its own models automatically on first ANPR request (needs
internet once). `GET /api/health` reports which components are active:

```json
{ "anpr_detector": "yolo", "super_resolution": true, "plate_reader": "easyocr" }
```

Every stage degrades gracefully: if a model or library is missing, ANPR falls
back to the classic CV + Tesseract path with no code changes.

> Tip: plate-reading accuracy still scales with input resolution. Upload the
> original high-resolution photo, not a small screenshot.

## Notes & limitations

- **ANPR** is most accurate with the deep-learning stack (YOLO + super-res +
  EasyOCR). Without it, it falls back to classic CV + Tesseract, which handles
  close-up Latin/clear plates but struggles with small or Arabic-Indic plates.
- Very worn / embossed / low-contrast plates may still read poorly regardless.
- **KYC** field extraction is heuristic/label-based; the **MRZ** parser
  (passports/TD3) is the most reliable signal when present.
- Tesseract struggles with handwriting, stylized fonts and noisy backgrounds.
