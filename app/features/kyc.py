"""KYC & Onboarding document extraction.

Extracts identity fields from passports, national IDs and driver licenses.
The most reliable signal on machine-readable documents is the MRZ (Machine
Readable Zone) at the bottom of passports/IDs (ICAO 9303), so we parse that
when present and otherwise fall back to heuristic field extraction.

Supports Iraqi Unified National Card (البطاقة الوطنية الموحدة) with Arabic/
Kurdish bilingual labels, TD1 MRZ (3×30), rotation correction, and EasyOCR.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..core import engine, preprocess

# ICAO 9303 MRZ uses '<' as filler. TD3 = 2×44, TD1 (ID card) = 3×30.
_MRZ_LINE = re.compile(r"^[A-Z0-9<]{28,44}$")
_MRZ_TD1_LINE = re.compile(r"^[A-Z0-9<]{28,32}$")

_ARABIC = r"[\u0600-\u06FF\u0750-\u077F\s\-]{2,40}"
_IRAQI_DATE = r"(\d{4}/\d{2}/\d{2})"

# Bilingual Arabic / Kurdish labels on the Iraqi national ID.
_FIELD_PATTERNS = {
    "name": re.compile(
        rf"(?:الاسم|ناو)(?:\s*/\s*[^\n:]*)?\s*[:\-]?\s*({_ARABIC})",
        re.UNICODE,
    ),
    "father_name": re.compile(
        rf"(?:الأ?ب|باوك)(?:\s*/\s*[^\n:]*)?\s*[:\-]?\s*({_ARABIC})",
        re.UNICODE,
    ),
    "grandfather_name": re.compile(
        rf"(?:الجد|باپیر|باپير)(?:\s*/\s*[^\n:]*)?\s*[:\-]?\s*({_ARABIC})",
        re.UNICODE,
    ),
    "surname": re.compile(
        rf"(?:اللقب|نازناو)(?:\s*/\s*[^\n:]*)?\s*[:\-]?\s*({_ARABIC})",
        re.UNICODE,
    ),
    "mother_name": re.compile(
        rf"(?:الأ?م|دايك)(?:\s*/\s*[^\n:]*)?\s*[:\-]?\s*({_ARABIC})",
        re.UNICODE,
    ),
    "gender": re.compile(
        r"(?:الجنس|ر[\u0600-\u06FF]+)(?:\s*/\s*[^\n:]*)?\s*[:\-]?\s*(ذكر|أ?نثى)",
        re.UNICODE,
    ),
    "blood_type": re.compile(
        r"(?:فصيلة\s*الدم|گرووپي\s*خوێن|گروپي\s*خون)(?:\s*/\s*[^\n:]*)?\s*[:\-]?\s*([+\-]?[ABO][+\-]?|[+\-][ABO])",
        re.I | re.UNICODE,
    ),
    "date_of_birth": re.compile(
        rf"(?:تاريخ\s*(?:ال)?(?:ولادة|الميلاد)|ڕۆژی\s*لەدایکبوون)(?:\s*/\s*[^\d]*)?\s*[:\-]?\s*{_IRAQI_DATE}",
        re.UNICODE,
    ),
    "expiry_date": re.compile(
        rf"(?:تاريخ\s*(?:ال)?(?:نفاذ|انتهاء|الانتهاء)|بەرواری\s*بەسەرچوون)(?:\s*/\s*[^\d]*)?\s*[:\-]?\s*{_IRAQI_DATE}",
        re.UNICODE,
    ),
    "date_of_issue": re.compile(
        rf"(?:تاريخ\s*(?:ال)?(?:إصدار|اصدار)|بەرواری\s*دەرچوون)(?:\s*/\s*[^\d]*)?\s*[:\-]?\s*{_IRAQI_DATE}",
        re.UNICODE,
    ),
    "place_of_birth": re.compile(
        rf"(?:محل\s*(?:ال)?ولادة|شوێنی\s*لەدایکبوون)(?:\s*/\s*[^:])*\s*:\s*({_ARABIC})",
        re.UNICODE,
    ),
    "issuing_authority": re.compile(
        rf"(?:جهة\s*(?:ال)?(?:إصدار|اصدار)|لایەنی\s*دەرچوون)\s*[^:]*:\s*({_ARABIC})",
        re.UNICODE,
    ),
    "family_number": re.compile(
        rf"(?:الرقم\s*(?:ال)?(?:عائلي|عائلى)|ژمارەی\s*خێزان)\s*[^:0-9]*[:\-]?\s*(\d{{4}}[A-Z]\d{{2}}[A-Z]\d{{10,14}})",
        re.I | re.UNICODE,
    ),
    # English fallbacks (passports, other IDs).
    "document_number": re.compile(
        r"(?:passport|id|licen[cs]e|document)\s*(?:no|number|#)\s*[:\-]?\s*([A-Z0-9]{5,15})",
        re.I,
    ),
}

# Iraqi front cards often print the value immediately before the bilingual label.
_VALUE_BEFORE_LABEL = {
    "name": re.compile(rf"({_ARABIC})\s+(?:الاسم|ناو)\s*/", re.UNICODE),
    "father_name": re.compile(rf"({_ARABIC})\s+الأ?ب\s*/", re.UNICODE),
    "grandfather_name": re.compile(rf"({_ARABIC})\s+الجد\s*/", re.UNICODE),
    "mother_name": re.compile(rf"({_ARABIC})\s+الأ?م\s*/", re.UNICODE),
    "surname": re.compile(
        rf"(?:/|:)\s*({_ARABIC})\s+(?:اللقب|نازناو)", re.UNICODE
    ),
    "gender": re.compile(r"(ذكر|أ?نثى)\s+الجنس\s*/", re.UNICODE),
}

_STANDALONE_PATTERNS = {
    "national_id": re.compile(r"\b(\d{12})\b"),
    "serial_number": re.compile(r"\b(AR\d{7})\b", re.I),
    "family_number": re.compile(r"\b(\d{4}[A-Z]\d{2}[A-Z]\d{10,14})\b", re.I),
}

# Signals used to pick the best card orientation.
_ROTATION_HINTS = re.compile(
    r"ID\s*IR\s*Q|IDIRQ|الاسم|ناو|تاريخ|الولادة|النفاذ|البطاقة|الوطنية|"
    r"AR\d{7}|\d{12}|\d{4}/\d{2}/\d{2}|AL[A-Z]{3,}",
    re.I | re.UNICODE,
)

_MRZ_NAME_FIXES = {
    "ALAXSSFR": "ALASFAR",
    "ALAXSFR": "ALASFAR",
    "ALAXSFAR": "ALASFAR",
    "ALASFR": "ALASFAR",
    "EMAR": "AMMAR",
}


@dataclass
class MRZData:
    document_type: str | None = None
    issuing_country: str | None = None
    surname: str | None = None
    given_names: str | None = None
    document_number: str | None = None
    nationality: str | None = None
    date_of_birth: str | None = None
    sex: str | None = None
    expiry_date: str | None = None
    national_id: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v}


@dataclass
class KYCResult:
    raw_text: str
    confidence: float
    fields: dict[str, str] = field(default_factory=dict)
    mrz: MRZData | None = None

    def to_dict(self) -> dict:
        return {
            "fields": self.fields,
            "mrz": self.mrz.to_dict() if self.mrz else None,
            "confidence": round(self.confidence, 2),
            "raw_text": self.raw_text,
        }


def _parse_mrz_date(raw: str) -> str | None:
    """MRZ dates are YYMMDD. Return YYYY/MM/DD (century guessed)."""
    if not re.fullmatch(r"[0-9]{6}", raw):
        return None
    yy, mm, dd = raw[:2], raw[2:4], raw[4:6]
    year = int(yy)
    century = 1900 if year > 30 else 2000
    return f"{century + year:04d}/{mm}/{dd}"


def _normalize_mrz_line(line: str) -> str:
    """Clean an OCR line into MRZ charset."""
    s = re.sub(r"\s+", "", line.upper())
    s = s.replace("«", "<").replace("»", "<").replace("@", "Q").replace("&", "Q")
    # EasyOCR often reads IDIRQ as 10IR@ / 10IRQ / 1DIRQ.
    if re.match(r"1[0O]I?R[@Q0O]?", s):
        s = "IDIRQ" + s[re.match(r"1[0O]I?R[@Q0O]?", s).end() :]  # type: ignore[union-attr]
    s = re.sub(r"[^A-Z0-9<]", "<", s)
    return s


def _fix_mrz_name(raw: str) -> str | None:
    if not raw:
        return None
    cleaned = raw.replace("<", " ").strip()
    if not cleaned:
        return None
    upper = cleaned.upper()
    if upper in _MRZ_NAME_FIXES:
        return _MRZ_NAME_FIXES[upper].title()
    # Generic cleanup: collapse fillers, fix doubled letters from OCR.
    upper = re.sub(r"\s+", " ", upper)
    if upper in _MRZ_NAME_FIXES:
        return _MRZ_NAME_FIXES[upper].title()
    return cleaned.title()


def _collect_mrz_lines(text: str) -> list[str]:
    lines: list[str] = []
    for ln in text.splitlines():
        norm = _normalize_mrz_line(ln)
        if _MRZ_LINE.match(norm):
            lines.append(norm)
    return lines


def parse_td1_mrz(lines: list[str]) -> MRZData | None:
    """Parse TD1 ID-card MRZ (3 lines × 30 characters)."""
    candidates = _collect_mrz_lines("\n".join(lines))
    td1 = [
        ln
        for ln in candidates
        if _MRZ_TD1_LINE.match(ln) and ("IRQ" in ln or "IDIR" in ln[:6])
    ]
    if len(td1) < 3:
        return None

    l1, l2, l3 = td1[-3], td1[-2], td1[-1]
    # Pad/truncate to 30 chars per ICAO spec.
    l1, l2, l3 = (ln.ljust(30, "<")[:30] for ln in (l1, l2, l3))

    mrz = MRZData()
    mrz.document_type = l1[0:2].replace("<", "") or None
    mrz.issuing_country = l1[2:5].replace("<", "") or None
    mrz.document_number = l1[5:14].replace("<", "").strip() or None

    optional = l1[15:30].replace("<", "")
    nid_match = re.search(r"\d{12}", optional)
    if nid_match:
        mrz.national_id = nid_match.group(0)

    if len(l2) >= 18:
        mrz.date_of_birth = _parse_mrz_date(l2[0:6])
        mrz.sex = l2[7:8].replace("<", "") or None
        mrz.expiry_date = _parse_mrz_date(l2[8:14])
        mrz.nationality = l2[15:18].replace("<", "") or None

    names = l3.split("<<", 1)
    mrz.surname = _fix_mrz_name(names[0])
    if len(names) > 1:
        given = names[1].split("<<")[0]
        mrz.given_names = _fix_mrz_name(given)

    return mrz


def parse_td3_mrz(lines: list[str]) -> MRZData | None:
    """Parse TD3 passport MRZ (2 lines × 44 characters)."""
    candidates = _collect_mrz_lines("\n".join(lines))
    long_lines = [ln for ln in candidates if len(ln) >= 40]
    if len(long_lines) < 2:
        return None

    l1, l2 = long_lines[-2], long_lines[-1]
    mrz = MRZData()

    mrz.document_type = l1[0:1].replace("<", "") or None
    mrz.issuing_country = l1[2:5].replace("<", "") or None
    names = l1[5:].split("<<", 1)
    if names:
        mrz.surname = _fix_mrz_name(names[0])
    if len(names) > 1:
        mrz.given_names = _fix_mrz_name(names[1])

    if len(l2) >= 28:
        mrz.document_number = l2[0:9].replace("<", "") or None
        mrz.nationality = l2[10:13].replace("<", "") or None
        mrz.date_of_birth = _parse_mrz_date(l2[13:19])
        mrz.sex = l2[20:21].replace("<", "") or None
        mrz.expiry_date = _parse_mrz_date(l2[21:27])

    return mrz


def parse_mrz(lines: list[str]) -> MRZData | None:
    """Parse MRZ — tries TD1 (Iraqi ID) first, then TD3 (passport)."""
    return parse_td1_mrz(lines) or parse_td3_mrz(lines)


def _clean_arabic_value(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    # Drop trailing label fragments accidentally captured.
    value = re.split(r"\s*(?:الأ?ب|الجد|اللقب|الأ?م|الجنس|فصيلة|تاريخ|محل|جهة|الرقم)\s", value)[0]
    return value.strip(" :-/")


def _normalize_blood_type(raw: str) -> str:
    raw = raw.strip().upper().replace("0", "O")
    if re.fullmatch(r"[+\-][ABO]", raw):
        return raw
    if re.fullmatch(r"[ABO][+\-]", raw):
        return raw[-1] + raw[0]
    return raw


def _field_quality(key: str, val: str) -> int:
    if not val:
        return 0
    if key == "serial_number":
        return 20 if re.fullmatch(r"AR\d{7}", val, re.I) else 0
    if key == "national_id":
        return 20 if re.fullmatch(r"\d{12}", val) else 0
    if key == "family_number":
        return 20 if re.fullmatch(r"\d{4}[A-Z]\d{2}[A-Z]\d{10,14}", val, re.I) else 0
    if key in ("date_of_birth", "date_of_issue", "expiry_date"):
        return 15 if re.fullmatch(r"\d{4}/\d{2}/\d{2}", val) else 0
    if key == "gender":
        return 10 if val in ("ذكر", "أنثى", "انثى") else 0
    if key == "blood_type":
        return 10 if re.fullmatch(r"[+\-][ABO]", val, re.I) else 0
    # Arabic personal names — penalize obvious Latin OCR garbage.
    if key in ("name", "father_name", "grandfather_name", "surname", "mother_name"):
        if re.search(r"[A-Za-z]{4,}", val):
            return 1
        return 10 if re.search(r"[\u0600-\u06FF]", val) else 3
    return 5


def _extract_fields(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for key, pattern in _FIELD_PATTERNS.items():
        match = pattern.search(text)
        if match:
            val = match.group(1).strip()
            if key in (
                "name", "father_name", "grandfather_name", "surname",
                "mother_name", "place_of_birth", "issuing_authority",
            ):
                val = _clean_arabic_value(val)
            if key == "blood_type":
                val = _normalize_blood_type(val)
            if val:
                found[key] = val

    for key, pattern in _VALUE_BEFORE_LABEL.items():
        if found.get(key):
            continue
        match = pattern.search(text)
        if match:
            val = _clean_arabic_value(match.group(1).strip())
            if val:
                found[key] = val

    for key, pattern in _STANDALONE_PATTERNS.items():
        if found.get(key):
            continue
        match = pattern.search(text)
        if match:
            found[key] = match.group(1).upper() if key == "serial_number" else match.group(1)

    _assign_unlabelled_dates(text, found)
    return found


def _assign_unlabelled_dates(text: str, found: dict[str, str]) -> None:
    """Assign YYYY/MM/DD dates by year range when labels were not matched."""
    dates = sorted(set(re.findall(_IRAQI_DATE, text)))
    if not dates:
        return
    for raw in dates:
        year = int(raw[:4])
        if not found.get("date_of_birth") and 1940 <= year <= 2010:
            found["date_of_birth"] = raw
    for raw in dates:
        year = int(raw[:4])
        if not found.get("date_of_issue") and 2010 <= year <= 2024:
            found["date_of_issue"] = raw
    for raw in dates:
        year = int(raw[:4])
        if not found.get("expiry_date") and year >= 2025:
            found["expiry_date"] = raw


def _score_rotation_text(text: str) -> float:
    score = 0.0
    compact = re.sub(r"\s+", "", text)
    if _ROTATION_HINTS.search(text) or _ROTATION_HINTS.search(compact):
        score += 40
    mrz_lines = _collect_mrz_lines(text)
    score += len(mrz_lines) * 15
    if re.search(r"IDIRQ|IDIRAQ", compact, re.I):
        score += 30
    score += min(len(text) / 50.0, 20.0)
    return score


def _auto_orient(img):
    """Pick 0/90/180/270° rotation that yields the strongest ID/MRZ signals."""
    osd = preprocess.osd_rotation(img)
    if osd:
        return preprocess.rotate_image(img, osd)

    import cv2

    best_angle = 0
    best_score = -1.0
    thumb = img
    h = img.shape[0]
    if h > 900:
        scale = 900 / h
        thumb = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    for angle in (0, 90, 180, 270):
        rotated = preprocess.rotate_image(thumb, angle)
        score = 0.0
        try:
            from . import easyocr_reader

            if easyocr_reader.is_available():
                e_text, e_conf = easyocr_reader.read_id_card(rotated)
                score = _score_rotation_text(e_text) + e_conf * 0.6
                if re.search(r"[\u0600-\u06FF]{3,}", e_text):
                    score += 25
        except Exception:
            pass
        if score < 40:
            try:
                quick = engine.run_ocr(
                    rotated, lang="eng+ara", psm=11, auto_fallback=False
                )
                score = max(
                    score, _score_rotation_text(quick.text) + quick.mean_confidence * 0.3
                )
            except Exception:
                pass
        if score > best_score:
            best_score = score
            best_angle = angle

    return preprocess.rotate_image(img, best_angle)


def _ocr_card_face(img, *, lang: str) -> tuple[str, float]:
    """Run Tesseract + EasyOCR on an oriented card image."""
    texts: list[str] = []
    confidences: list[float] = []

    tess = engine.run_ocr(img, lang=lang, psm=3)
    if tess.text.strip():
        texts.append(tess.text)
        confidences.append(tess.mean_confidence)

    try:
        from . import easyocr_reader

        if easyocr_reader.is_available():
            e_text, e_conf = easyocr_reader.read_id_card(img)
            if e_text.strip():
                texts.append(e_text)
                confidences.append(e_conf)
    except Exception:
        pass

    combined = "\n".join(texts)
    conf = max(confidences) if confidences else 0.0
    return combined, conf


def _ocr_mrz_zone(img) -> str:
    """OCR the lower portion of the card where the MRZ usually sits."""
    h = img.shape[0]
    crop = img[int(h * 0.50) :, :]
    parts: list[str] = []

    mrz_tess = engine.run_ocr(crop, lang="eng", psm=6, preprocess_mode="otsu")
    if mrz_tess.text.strip():
        parts.append(mrz_tess.text)

    try:
        from . import easyocr_reader

        if easyocr_reader.is_available():
            e_text, _ = easyocr_reader.read_id_card(crop)
            if e_text.strip():
                parts.append(e_text)
    except Exception:
        pass

    return "\n".join(parts)


def _merge_fields(base: dict[str, str], extra: dict[str, str]) -> dict[str, str]:
    merged = dict(base)
    for key, val in extra.items():
        if not val:
            continue
        cur = merged.get(key)
        if not cur:
            merged[key] = val
            continue
        q_new, q_cur = _field_quality(key, val), _field_quality(key, cur)
        if q_new > q_cur or (q_new == q_cur and len(val) > len(cur)):
            merged[key] = val
    return merged


def _apply_mrz(fields: dict[str, str], mrz: MRZData | None) -> None:
    if not mrz:
        return
    if mrz.document_number and not fields.get("serial_number"):
        fields["serial_number"] = mrz.document_number.upper()
    if mrz.national_id and not fields.get("national_id"):
        fields["national_id"] = mrz.national_id
    if mrz.date_of_birth and not fields.get("date_of_birth"):
        fields["date_of_birth"] = mrz.date_of_birth
    if mrz.expiry_date and not fields.get("expiry_date"):
        fields["expiry_date"] = mrz.expiry_date
    if mrz.given_names and not fields.get("name"):
        fields["name"] = mrz.given_names
    if mrz.surname and not fields.get("surname"):
        fields["surname"] = mrz.surname
    if mrz.sex and not fields.get("gender"):
        fields["gender"] = "ذكر" if mrz.sex.upper() == "M" else "أنثى"


def _process_image(img, *, lang: str) -> tuple[str, float, dict[str, str], MRZData | None]:
    oriented = _auto_orient(img)
    text, conf = _ocr_card_face(oriented, lang=lang)
    mrz_text = _ocr_mrz_zone(oriented)
    full_text = text + "\n" + mrz_text

    fields = _extract_fields(full_text)
    mrz = parse_mrz(full_text.splitlines())
    _apply_mrz(fields, mrz)
    return full_text, conf, fields, mrz


def extract_identity(
    data: bytes,
    *,
    lang: str = "eng+ara",
    extra_images: list[bytes] | None = None,
) -> KYCResult:
    """Extract identity fields from one or more ID document images (raw bytes)."""
    engine.ensure_available()

    all_bytes = [data] + list(extra_images or [])
    texts: list[str] = []
    confidences: list[float] = []
    merged_fields: dict[str, str] = {}
    best_mrz: MRZData | None = None

    for blob in all_bytes:
        img = preprocess.to_cv_image(blob)
        text, conf, fields, mrz = _process_image(img, lang=lang)
        texts.append(text)
        confidences.append(conf)
        merged_fields = _merge_fields(merged_fields, fields)
        if mrz and (
            best_mrz is None
            or (mrz.issuing_country == "IRQ" and best_mrz.issuing_country != "IRQ")
            or (mrz.national_id and not best_mrz.national_id)
        ):
            best_mrz = mrz

    _apply_mrz(merged_fields, best_mrz)
    mean_conf = float(max(confidences)) if confidences else 0.0
    if merged_fields:
        mean_conf = max(mean_conf, 70.0)

    return KYCResult(
        raw_text="\n---\n".join(texts),
        confidence=mean_conf,
        fields=merged_fields,
        mrz=best_mrz,
    )
