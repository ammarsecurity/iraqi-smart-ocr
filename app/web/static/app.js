"use strict";

const files = { ocr: null, anpr: null, kyc: null };

// ---- Static ANPR ROI (matches live camera) ----------------------------------
const ANPR_ROI_STORAGE_PREFIX = "anpr-roi-";
const ANPR_ROI_MIN_FRAC = 0.2;
const ANPR_ROI_JPEG_QUALITY = 0.85;
const ANPR_ROI_PRESETS = {
  center: { x: 0.15, y: 0.35, w: 0.7, h: 0.3 },
  bottom: { x: 0.1, y: 0.55, w: 0.8, h: 0.4 },
  full: { x: 0, y: 0, w: 1, h: 1 },
};

const anprPreviewWrap = document.getElementById("anpr-preview-wrap");
const anprPreviewImg = document.getElementById("anpr-preview-img");
const anprRoiBox = document.getElementById("anpr-roi-box");
const anprFilename = document.getElementById("anpr-filename");
const anprRoiPresets = document.getElementById("anpr-roi-presets");
const anprRoiPresetBtns = document.querySelectorAll('.roi-preset-btn[data-roi-scope="anpr"]');

let anprCurrentRoi = { ...ANPR_ROI_PRESETS.center };
let anprRoiDrag = null;
let anprImageW = 0;
let anprImageH = 0;
let anprPreviewUrl = null;

function anprRoiStorageKey() {
  if (anprImageW && anprImageH) {
    return `${ANPR_ROI_STORAGE_PREFIX}upload-${anprImageW}x${anprImageH}`;
  }
  return `${ANPR_ROI_STORAGE_PREFIX}upload`;
}

function clampAnprRoi(roi) {
  let { x, y, w, h } = roi;
  w = Math.max(ANPR_ROI_MIN_FRAC, Math.min(1, w));
  h = Math.max(ANPR_ROI_MIN_FRAC, Math.min(1, h));
  x = Math.max(0, Math.min(1 - w, x));
  y = Math.max(0, Math.min(1 - h, y));
  return { x, y, w, h };
}

function loadAnprRoi() {
  for (const key of [anprRoiStorageKey(), `${ANPR_ROI_STORAGE_PREFIX}upload`]) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) continue;
      const parsed = JSON.parse(raw);
      if (
        typeof parsed.x === "number" &&
        typeof parsed.y === "number" &&
        typeof parsed.w === "number" &&
        typeof parsed.h === "number"
      ) {
        return clampAnprRoi(parsed);
      }
    } catch {
      /* ignore */
    }
  }
  return null;
}

function saveAnprRoi() {
  try {
    localStorage.setItem(anprRoiStorageKey(), JSON.stringify(anprCurrentRoi));
    localStorage.setItem(`${ANPR_ROI_STORAGE_PREFIX}upload`, JSON.stringify(anprCurrentRoi));
  } catch {
    /* ignore */
  }
}

function detectAnprPreset(roi) {
  for (const [key, preset] of Object.entries(ANPR_ROI_PRESETS)) {
    const match =
      Math.abs(roi.x - preset.x) < 0.02 &&
      Math.abs(roi.y - preset.y) < 0.02 &&
      Math.abs(roi.w - preset.w) < 0.02 &&
      Math.abs(roi.h - preset.h) < 0.02;
    if (match) return key;
  }
  return "";
}

function updateAnprPresetButtons() {
  const preset = detectAnprPreset(anprCurrentRoi);
  anprRoiPresetBtns.forEach((btn) => {
    btn.classList.toggle("roi-preset-btn--active", btn.dataset.preset === preset);
  });
}

function anprPreviewWrapEl() {
  return anprPreviewWrap;
}

function getAnprContainMapping(srcW, srcH) {
  const wrap = anprPreviewWrapEl();
  const elW = wrap.clientWidth;
  const elH = wrap.clientHeight;
  const scale = Math.min(elW / srcW, elH / srcH);
  const scaledW = srcW * scale;
  const scaledH = srcH * scale;
  return {
    scale,
    offsetX: (elW - scaledW) / 2,
    offsetY: (elH - scaledH) / 2,
    elW,
    elH,
    srcW,
    srcH,
  };
}

function anprNormToDisplay(normX, normY, normW, normH, srcW, srcH) {
  const m = getAnprContainMapping(srcW, srcH);
  return {
    left: m.offsetX + normX * srcW * m.scale,
    top: m.offsetY + normY * srcH * m.scale,
    width: normW * srcW * m.scale,
    height: normH * srcH * m.scale,
  };
}

function anprDisplayRectToNorm(left, top, width, height, srcW, srcH) {
  const m = getAnprContainMapping(srcW, srcH);
  return {
    x: (left - m.offsetX) / (srcW * m.scale),
    y: (top - m.offsetY) / (srcH * m.scale),
    w: width / (srcW * m.scale),
    h: height / (srcH * m.scale),
  };
}

function updateAnprRoiDisplay() {
  if (!anprRoiBox || !anprImageW || !anprImageH) return;
  const rect = anprNormToDisplay(
    anprCurrentRoi.x,
    anprCurrentRoi.y,
    anprCurrentRoi.w,
    anprCurrentRoi.h,
    anprImageW,
    anprImageH
  );
  anprRoiBox.style.left = `${rect.left}px`;
  anprRoiBox.style.top = `${rect.top}px`;
  anprRoiBox.style.width = `${rect.width}px`;
  anprRoiBox.style.height = `${rect.height}px`;
}

function applyAnprRoi(roi, { persist = true } = {}) {
  anprCurrentRoi = clampAnprRoi({ ...roi });
  updateAnprRoiDisplay();
  updateAnprPresetButtons();
  if (persist) saveAnprRoi();
}

function applyAnprRoiPreset(name) {
  const preset = ANPR_ROI_PRESETS[name];
  if (!preset) return;
  applyAnprRoi(preset);
}

function anprRoiPointerTarget(ev) {
  const handle = ev.target.closest(".roi-handle");
  if (handle) return handle.dataset.handle;
  if (ev.target.closest(".roi-box__label")) return "move";
  if (ev.target === anprRoiBox || ev.target.closest(".roi-box") === anprRoiBox) return "move";
  return null;
}

function onAnprRoiPointerDown(ev) {
  if (!anprImageW || !anprImageH) return;
  const mode = anprRoiPointerTarget(ev);
  if (!mode) return;
  ev.preventDefault();
  ev.stopPropagation();
  const rect = anprRoiBox.getBoundingClientRect();
  const wrapRect = anprPreviewWrapEl().getBoundingClientRect();
  anprRoiDrag = {
    mode,
    pointerId: ev.pointerId,
    startX: ev.clientX,
    startY: ev.clientY,
    startRoi: { ...anprCurrentRoi },
    startRect: {
      left: rect.left - wrapRect.left,
      top: rect.top - wrapRect.top,
      width: rect.width,
      height: rect.height,
    },
    srcW: anprImageW,
    srcH: anprImageH,
  };
  anprRoiBox.setPointerCapture(ev.pointerId);
}

function onAnprRoiPointerMove(ev) {
  if (!anprRoiDrag || ev.pointerId !== anprRoiDrag.pointerId) return;
  ev.preventDefault();
  const dx = ev.clientX - anprRoiDrag.startX;
  const dy = ev.clientY - anprRoiDrag.startY;
  const m = getAnprContainMapping(anprRoiDrag.srcW, anprRoiDrag.srcH);
  const normDx = dx / (anprRoiDrag.srcW * m.scale);
  const normDy = dy / (anprRoiDrag.srcH * m.scale);
  const s = anprRoiDrag.startRoi;
  let x = s.x;
  let y = s.y;
  let w = s.w;
  let h = s.h;

  if (anprRoiDrag.mode === "move") {
    x = s.x + normDx;
    y = s.y + normDy;
  } else {
    const r = anprRoiDrag.startRect;
    let left = r.left + dx;
    let top = r.top + dy;
    let width = r.width;
    let height = r.height;
    const mode = anprRoiDrag.mode;

    if (mode.includes("e")) width = r.width + dx;
    if (mode.includes("w")) {
      width = r.width - dx;
      left = r.left + dx;
    }
    if (mode.includes("s")) height = r.height + dy;
    if (mode.includes("n")) {
      height = r.height - dy;
      top = r.top + dy;
    }

    const norm = anprDisplayRectToNorm(left, top, width, height, anprRoiDrag.srcW, anprRoiDrag.srcH);
    x = norm.x;
    y = norm.y;
    w = norm.w;
    h = norm.h;
  }

  anprCurrentRoi = clampAnprRoi({ x, y, w, h });
  updateAnprRoiDisplay();
  updateAnprPresetButtons();
}

function onAnprRoiPointerUp(ev) {
  if (!anprRoiDrag || ev.pointerId !== anprRoiDrag.pointerId) return;
  try {
    anprRoiBox.releasePointerCapture(ev.pointerId);
  } catch {
    /* ignore */
  }
  anprRoiDrag = null;
  saveAnprRoi();
}

function loadImageElement(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Failed to load image"));
    };
    img.src = url;
  });
}

function cropAnprFile(file, roi) {
  return loadImageElement(file).then(
    (img) =>
      new Promise((resolve, reject) => {
        const w = img.naturalWidth;
        const h = img.naturalHeight;
        const padX = Math.round(roi.w * w * 0.08);
        const padY = Math.round(roi.h * h * 0.04);
        let cropX = Math.round(roi.x * w) - padX;
        let cropY = Math.round(roi.y * h) - padY;
        let cropW = Math.round(roi.w * w) + padX * 2;
        let cropH = Math.round(roi.h * h) + padY * 2;
        cropX = Math.max(0, cropX);
        cropY = Math.max(0, cropY);
        cropW = Math.min(w - cropX, cropW);
        cropH = Math.min(h - cropY, cropH);

        const canvas = document.createElement("canvas");
        canvas.width = cropW;
        canvas.height = cropH;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, cropX, cropY, cropW, cropH, 0, 0, cropW, cropH);

        canvas.toBlob(
          (blob) => {
            if (!blob) {
              reject(new Error("Failed to crop image"));
              return;
            }
            const base = file.name.replace(/\.[^.]+$/, "") || "plate";
            resolve(new File([blob], `${base}-roi.jpg`, { type: "image/jpeg" }));
          },
          "image/jpeg",
          ANPR_ROI_JPEG_QUALITY
        );
      })
  );
}

function setAnprPreview(file) {
  if (anprPreviewUrl) URL.revokeObjectURL(anprPreviewUrl);
  anprPreviewUrl = URL.createObjectURL(file);
  anprPreviewImg.src = anprPreviewUrl;
  anprFilename.textContent = file.name;
  anprFilename.hidden = false;
  anprPreviewWrap.hidden = false;
  if (anprRoiPresets) anprRoiPresets.hidden = false;
  const dropzone = document.getElementById("anpr-dropzone");
  if (dropzone) dropzone.classList.add("anpr-dropzone--ready");

  const onReady = () => {
    anprImageW = anprPreviewImg.naturalWidth;
    anprImageH = anprPreviewImg.naturalHeight;
    const saved = loadAnprRoi();
    anprCurrentRoi = saved ? saved : { ...ANPR_ROI_PRESETS.center };
    updateAnprRoiDisplay();
    updateAnprPresetButtons();
  };

  if (anprPreviewImg.complete && anprPreviewImg.naturalWidth) onReady();
  else anprPreviewImg.onload = onReady;
}

if (anprRoiBox) {
  anprRoiBox.addEventListener("pointerdown", onAnprRoiPointerDown);
  anprRoiBox.addEventListener("pointermove", onAnprRoiPointerMove);
  anprRoiBox.addEventListener("pointerup", onAnprRoiPointerUp);
  anprRoiBox.addEventListener("pointercancel", onAnprRoiPointerUp);
}

anprRoiPresetBtns.forEach((btn) => {
  btn.addEventListener("click", (ev) => {
    ev.stopPropagation();
    applyAnprRoiPreset(btn.dataset.preset);
  });
});

window.addEventListener("resize", () => {
  if (anprImageW && anprImageH) updateAnprRoiDisplay();
});

// ---- Engine status ----------------------------------------------------------
async function checkHealth() {
  const el = document.getElementById("status");
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    if (data.tesseract_version) {
      el.textContent = `Engine ready · Tesseract ${data.tesseract_version}`;
      el.className = "status status--ok";
    } else {
      el.textContent = "Tesseract not found — see README";
      el.className = "status status--down";
    }
  } catch {
    el.textContent = "Server unreachable";
    el.className = "status status--down";
  }
}

// ---- Tabs -------------------------------------------------------------------
document.querySelectorAll("button.tab[data-tab]").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll("button.tab[data-tab]").forEach((t) => t.classList.remove("tab--active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("panel--active"));
    tab.classList.add("tab--active");
    document.getElementById("panel-" + tab.dataset.tab).classList.add("panel--active");
  });
});

// ---- Dropzones --------------------------------------------------------------
document.querySelectorAll(".dropzone").forEach((zone) => {
  const inputId = zone.dataset.input;
  const input = document.getElementById(inputId);
  const key = inputId.split("-")[0];
  const runBtn = document.querySelector(`.run[data-action="${key}"]`);

  const setFile = (file) => {
    if (!file) return;
    files[key] = file;
    zone.classList.add("has-file");
    if (key === "anpr") {
      setAnprPreview(file);
    } else {
      const url = URL.createObjectURL(file);
      zone.innerHTML = `<p>${file.name}</p><img src="${url}" alt="preview" />`;
    }
    if (runBtn) runBtn.disabled = false;
  };

  zone.addEventListener("click", (e) => {
    if (key === "anpr" && e.target.closest(".roi-box, .roi-handle")) return;
    input.click();
  });
  input.addEventListener("change", (e) => setFile(e.target.files[0]));
  ["dragover", "dragenter"].forEach((ev) =>
    zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("drag"); })
  );
  ["dragleave", "drop"].forEach((ev) =>
    zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove("drag"); })
  );
  zone.addEventListener("drop", (e) => setFile(e.dataTransfer.files[0]));
});

// ---- Helpers ----------------------------------------------------------------
function confBadge(conf) {
  if (conf == null) return "";
  const cls = conf >= 80 ? "good" : conf >= 50 ? "warn" : "bad";
  return `<span class="badge ${cls}">confidence ${conf}%</span>`;
}
function hasArabic(s) { return /[\u0600-\u06FF]/.test(s || ""); }

async function postFile(url, file, extra = {}) {
  const fd = new FormData();
  fd.append("file", file);
  Object.entries(extra).forEach(([k, v]) => fd.append(k, v));
  const res = await fetch(url, { method: "POST", body: fd });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}

function setBusy(target, btn) {
  target.innerHTML = `<p class="muted"><span class="spinner"></span> Processing…</p>`;
  if (btn) btn.disabled = true;
}

// ---- Actions ----------------------------------------------------------------
document.querySelectorAll(".run").forEach((btn) => {
  btn.addEventListener("click", () => handlers[btn.dataset.action](btn));
});

const handlers = {
  async ocr(btn) {
    const out = document.getElementById("ocr-result");
    if (!files.ocr) return;
    setBusy(out, btn);
    try {
      const data = await postFile("/api/ocr", files.ocr, {
        lang: document.getElementById("ocr-lang").value,
        psm: document.getElementById("ocr-psm").value,
        preprocess: document.getElementById("ocr-pre").checked,
      });
      const dir = hasArabic(data.text) ? "rtl" : "ltr";
      out.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
          <strong>Extracted text</strong> ${confBadge(data.mean_confidence)}
        </div>
        <p class="muted" style="margin-bottom:8px">${data.word_count} words · lang: ${data.language}</p>
        <pre dir="${dir}">${escapeHtml(data.text) || "(no text detected)"}</pre>`;
    } catch (e) { out.innerHTML = errBox(e); }
    finally { btn.disabled = false; }
  },

  async anpr(btn) {
    const out = document.getElementById("anpr-result");
    if (!files.anpr) return;
    setBusy(out, btn);
    try {
      const cropped = await cropAnprFile(files.anpr, anprCurrentRoi);
      const data = await postFile("/api/anpr", cropped, { user_cropped: "true" });
      if (!data.best_plate) {
        out.innerHTML = `<p class="muted">No license plate detected. Try a clearer, closer photo.</p>`;
        return;
      }
      const others = (data.candidates || [])
        .filter((c) => c.plate && c.plate !== data.best_plate)
        .slice(0, 4)
        .map((c) =>
          `<div class="kv"><span class="k">${escapeHtml(c.text || c.plate)}</span><span class="v">${confBadge(c.confidence)}</span></div>`
        ).join("");
      const raw = data.raw_text
        ? `<p class="muted" style="margin-top:16px">Full OCR text</p><pre dir="${hasArabic(data.raw_text) ? "rtl" : "ltr"}">${escapeHtml(data.raw_text)}</pre>`
        : "";
      out.innerHTML = `
        <strong>Detected plate</strong>
        <div class="plate" dir="ltr">${escapeHtml(data.best_plate)}</div>
        <div style="text-align:center;margin-top:6px">${confBadge(data.best_confidence)}</div>
        ${others ? `<p class="muted" style="margin-top:16px">Other candidates</p>${others}` : ""}
        ${raw}`;
    } catch (e) { out.innerHTML = errBox(e); }
    finally { btn.disabled = false; }
  },

  async kyc(btn) {
    const out = document.getElementById("kyc-result");
    if (!files.kyc) return;
    setBusy(out, btn);
    try {
      const data = await postFile("/api/kyc", files.kyc, {
        lang: document.getElementById("kyc-lang").value,
      });
      const fields = Object.entries(data.fields || {});
      const fieldRows = fields.length
        ? fields.map(([k, v]) =>
            `<div class="kv"><span class="k">${escapeHtml(k)}</span><span class="v">${escapeHtml(v)}</span></div>`
          ).join("")
        : `<p class="muted">No labelled fields matched.</p>`;
      let mrzRows = "";
      if (data.mrz) {
        const entries = Object.entries(data.mrz).filter(([, v]) => v);
        if (entries.length) {
          mrzRows = `<p class="muted" style="margin-top:16px">MRZ (machine-readable zone)</p>` +
            entries.map(([k, v]) =>
              `<div class="kv"><span class="k">${escapeHtml(k)}</span><span class="v">${escapeHtml(String(v))}</span></div>`
            ).join("");
        }
      }
      out.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <strong>Extracted identity</strong> ${confBadge(data.confidence)}
        </div>
        ${fieldRows}
        ${mrzRows}`;
    } catch (e) { out.innerHTML = errBox(e); }
    finally { btn.disabled = false; }
  },
};

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function errBox(e) {
  return `<p class="badge bad" style="display:block;padding:12px">${escapeHtml(e.message)}</p>`;
}

checkHealth();
