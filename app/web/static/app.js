"use strict";

const files = { ocr: null, anpr: null, kyc: null };

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
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("tab--active"));
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
    const url = URL.createObjectURL(file);
    zone.innerHTML = `<p>${file.name}</p><img src="${url}" alt="preview" />`;
    if (runBtn) runBtn.disabled = false;
  };

  zone.addEventListener("click", () => input.click());
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
      const data = await postFile("/api/anpr", files.anpr);
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
