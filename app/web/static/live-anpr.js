"use strict";

const CAPTURE_INTERVAL_MS = 2000;
const MIN_MANUAL_SCAN_MS = 1000;
const MAX_FRAME_WIDTH = 1280;
const JPEG_QUALITY = 0.85;
const ROI_STORAGE_PREFIX = "anpr-roi-";
const ROI_MIN_FRAC = 0.2;

const ROI_PRESETS = {
  center: { x: 0.15, y: 0.35, w: 0.7, h: 0.3 },
  bottom: { x: 0.1, y: 0.55, w: 0.8, h: 0.4 },
  full: { x: 0, y: 0, w: 1, h: 1 },
};

const video = document.getElementById("video");
const canvas = document.getElementById("capture");
const ctx = canvas.getContext("2d");
const toggleBtn = document.getElementById("toggle-btn");
const scanBtn = document.getElementById("scan-btn");
const overlay = document.getElementById("video-overlay");
const plateBox = document.getElementById("plate-box");
const roiLayer = document.getElementById("roi-layer");
const roiBox = document.getElementById("roi-box");
const roiPresetBtns = document.querySelectorAll(".roi-preset-btn");
const scanStatus = document.getElementById("scan-status");
const plateDisplay = document.getElementById("plate-display");
const confDisplay = document.getElementById("conf-display");
const timeDisplay = document.getElementById("time-display");
const fpsLabel = document.getElementById("fps-label");
const throttleLabel = document.getElementById("throttle-label");
const wsLabel = document.getElementById("ws-label");
const cameraSelect = document.getElementById("camera-select");

let stream = null;
let ws = null;
let captureTimer = null;
let cameraOn = false;
let scanning = false;
let framesSent = 0;
let framesSkipped = 0;
let fpsTimer = null;
let lastFpsTick = Date.now();
let lastManualScan = 0;
let lastCaptureW = 0;
let lastCaptureH = 0;
let lastFullCaptureW = 0;
let lastFullCaptureH = 0;
let lastPlateBox = null;
let selectedDeviceId = "";
let switchingCamera = false;
let currentRoi = { ...ROI_PRESETS.center };
let roiDrag = null;

function wsUrl() {
  return OcrAuth.wsUrl("/ws/anpr");
}

function confBadge(conf) {
  if (conf == null) return "";
  const cls = conf >= 80 ? "good" : conf >= 50 ? "warn" : "bad";
  return `<span class="badge ${cls}">confidence ${conf}%</span>`;
}

function formatTimestamp(date = new Date()) {
  return date.toLocaleString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function setScanStatus(kind, text) {
  scanStatus.textContent = text;
  scanStatus.className = `scan-status scan-status--${kind}`;
}

function setWsLabel(text, ok) {
  wsLabel.textContent = `WebSocket: ${text}`;
  wsLabel.className = ok ? "meta-pill meta-pill--ok" : "meta-pill meta-pill--muted";
}

function hidePlateBox() {
  lastPlateBox = null;
  plateBox.hidden = true;
}

function videoWrap() {
  return video.parentElement;
}

function referenceVideoSize() {
  if (video.videoWidth && video.videoHeight) {
    return { w: video.videoWidth, h: video.videoHeight };
  }
  return { w: 16, h: 10 };
}

function getCoverMapping(srcW, srcH) {
  const elW = videoWrap().clientWidth;
  const elH = videoWrap().clientHeight;
  const scale = Math.max(elW / srcW, elH / srcH);
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

function normToDisplay(normX, normY, normW, normH, srcW, srcH) {
  const m = getCoverMapping(srcW, srcH);
  return {
    left: m.offsetX + normX * srcW * m.scale,
    top: m.offsetY + normY * srcH * m.scale,
    width: normW * srcW * m.scale,
    height: normH * srcH * m.scale,
  };
}

function displayRectToNorm(left, top, width, height, srcW, srcH) {
  const m = getCoverMapping(srcW, srcH);
  return {
    x: (left - m.offsetX) / (srcW * m.scale),
    y: (top - m.offsetY) / (srcH * m.scale),
    w: width / (srcW * m.scale),
    h: height / (srcH * m.scale),
  };
}

function clampRoi(roi) {
  let { x, y, w, h } = roi;
  w = Math.max(ROI_MIN_FRAC, Math.min(1, w));
  h = Math.max(ROI_MIN_FRAC, Math.min(1, h));
  x = Math.max(0, Math.min(1 - w, x));
  y = Math.max(0, Math.min(1 - h, y));
  return { x, y, w, h };
}

function roiStorageKey(deviceId) {
  return `${ROI_STORAGE_PREFIX}${deviceId || "default"}`;
}

function loadRoiForDevice(deviceId) {
  try {
    const raw = localStorage.getItem(roiStorageKey(deviceId));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (
      typeof parsed.x === "number" &&
      typeof parsed.y === "number" &&
      typeof parsed.w === "number" &&
      typeof parsed.h === "number"
    ) {
      return clampRoi(parsed);
    }
  } catch {
    /* ignore */
  }
  return null;
}

function saveRoiForDevice(deviceId) {
  if (!deviceId) return;
  try {
    localStorage.setItem(roiStorageKey(deviceId), JSON.stringify(currentRoi));
  } catch {
    /* ignore */
  }
}

function detectActivePreset(roi) {
  for (const [key, preset] of Object.entries(ROI_PRESETS)) {
    const match =
      Math.abs(roi.x - preset.x) < 0.02 &&
      Math.abs(roi.y - preset.y) < 0.02 &&
      Math.abs(roi.w - preset.w) < 0.02 &&
      Math.abs(roi.h - preset.h) < 0.02;
    if (match) return key;
  }
  return "";
}

function updatePresetButtons() {
  const preset = detectActivePreset(currentRoi);
  roiPresetBtns.forEach((btn) => {
    btn.classList.toggle("roi-preset-btn--active", btn.dataset.preset === preset);
  });
}

function applyRoi(roi, { persist = true } = {}) {
  currentRoi = clampRoi({ ...roi });
  updateRoiDisplay();
  updatePresetButtons();
  if (persist && selectedDeviceId) saveRoiForDevice(selectedDeviceId);
  if (lastPlateBox) showPlateBox(lastPlateBox);
}

function applyRoiPreset(name) {
  const preset = ROI_PRESETS[name];
  if (!preset) return;
  applyRoi(preset);
}

function loadRoiForCurrentDevice() {
  const saved = loadRoiForDevice(selectedDeviceId);
  if (saved) {
    currentRoi = saved;
  } else {
    currentRoi = { ...ROI_PRESETS.center };
  }
  updateRoiDisplay();
  updatePresetButtons();
}

function setRoiLayerMode(active) {
  roiLayer.classList.toggle("roi-layer--active", active);
  roiLayer.classList.toggle("roi-layer--placeholder", !active);
}

function updateRoiDisplay() {
  const { w: srcW, h: srcH } = referenceVideoSize();
  const rect = normToDisplay(currentRoi.x, currentRoi.y, currentRoi.w, currentRoi.h, srcW, srcH);
  roiBox.style.left = `${rect.left}px`;
  roiBox.style.top = `${rect.top}px`;
  roiBox.style.width = `${rect.width}px`;
  roiBox.style.height = `${rect.height}px`;
}

function roiPointerTarget(ev) {
  const handle = ev.target.closest(".roi-handle");
  if (handle) return handle.dataset.handle;
  if (ev.target.closest(".roi-box__label")) return "move";
  if (ev.target === roiBox || ev.target.closest(".roi-box") === roiBox) return "move";
  return null;
}

function onRoiPointerDown(ev) {
  if (!cameraOn) return;
  const mode = roiPointerTarget(ev);
  if (!mode) return;
  ev.preventDefault();
  const { w: srcW, h: srcH } = referenceVideoSize();
  const rect = roiBox.getBoundingClientRect();
  const wrapRect = videoWrap().getBoundingClientRect();
  roiDrag = {
    mode,
    pointerId: ev.pointerId,
    startX: ev.clientX,
    startY: ev.clientY,
    startRoi: { ...currentRoi },
    startRect: {
      left: rect.left - wrapRect.left,
      top: rect.top - wrapRect.top,
      width: rect.width,
      height: rect.height,
    },
    srcW,
    srcH,
  };
  roiBox.setPointerCapture(ev.pointerId);
}

function onRoiPointerMove(ev) {
  if (!roiDrag || ev.pointerId !== roiDrag.pointerId) return;
  ev.preventDefault();
  const dx = ev.clientX - roiDrag.startX;
  const dy = ev.clientY - roiDrag.startY;
  const m = getCoverMapping(roiDrag.srcW, roiDrag.srcH);
  const normDx = dx / (roiDrag.srcW * m.scale);
  const normDy = dy / (roiDrag.srcH * m.scale);
  const s = roiDrag.startRoi;
  let x = s.x;
  let y = s.y;
  let w = s.w;
  let h = s.h;

  if (roiDrag.mode === "move") {
    x = s.x + normDx;
    y = s.y + normDy;
  } else {
    const r = roiDrag.startRect;
    let left = r.left + dx;
    let top = r.top + dy;
    let width = r.width;
    let height = r.height;
    const mode = roiDrag.mode;

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

    const norm = displayRectToNorm(left, top, width, height, roiDrag.srcW, roiDrag.srcH);
    x = norm.x;
    y = norm.y;
    w = norm.w;
    h = norm.h;
  }

  currentRoi = clampRoi({ x, y, w, h });
  updateRoiDisplay();
  updatePresetButtons();
}

function onRoiPointerUp(ev) {
  if (!roiDrag || ev.pointerId !== roiDrag.pointerId) return;
  try {
    roiBox.releasePointerCapture(ev.pointerId);
  } catch {
    /* ignore */
  }
  roiDrag = null;
  saveRoiForDevice(selectedDeviceId);
  if (lastPlateBox) showPlateBox(lastPlateBox);
}

function showPlateBox(box) {
  if (!box || box.length < 4 || !lastCaptureW || !lastCaptureH) {
    hidePlateBox();
    return;
  }
  const { w: srcW, h: srcH } = referenceVideoSize();
  const [bx, by, bw, bh] = box;
  const normX = currentRoi.x + (bx / lastCaptureW) * currentRoi.w;
  const normY = currentRoi.y + (by / lastCaptureH) * currentRoi.h;
  const normW = (bw / lastCaptureW) * currentRoi.w;
  const normH = (bh / lastCaptureH) * currentRoi.h;
  const rect = normToDisplay(normX, normY, normW, normH, srcW, srcH);
  plateBox.style.left = `${rect.left}px`;
  plateBox.style.top = `${rect.top}px`;
  plateBox.style.width = `${rect.width}px`;
  plateBox.style.height = `${rect.height}px`;
  plateBox.hidden = false;
  lastPlateBox = box;
}

function connectWs() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  ws = new WebSocket(wsUrl());
  ws.binaryType = "arraybuffer";

  ws.addEventListener("open", () => setWsLabel("connected", true));
  ws.addEventListener("close", () => {
    setWsLabel("disconnected", false);
    if (cameraOn) setTimeout(connectWs, 1500);
  });
  ws.addEventListener("error", () => setWsLabel("error", false));
  ws.addEventListener("message", (ev) => {
    let data;
    try {
      data = JSON.parse(ev.data);
    } catch {
      return;
    }
    handleServerMessage(data);
  });
}

function handleServerMessage(data) {
  if (data.status === "scanning") {
    scanning = true;
    scanBtn.disabled = true;
    setScanStatus("scanning", "Scanning…");
    return;
  }
  if (data.status === "busy") {
    framesSkipped += 1;
    updateThrottleLabel();
    return;
  }
  if (data.status === "error") {
    scanning = false;
    scanBtn.disabled = !cameraOn;
    hidePlateBox();
    setScanStatus("error", data.detail || "Error");
    return;
  }
  if (data.status !== "result") return;

  scanning = false;
  scanBtn.disabled = !cameraOn;
  const ts = formatTimestamp();
  timeDisplay.textContent = `Last scan: ${ts}`;

  if (data.best_plate) {
    plateDisplay.textContent = data.best_plate;
    plateDisplay.classList.remove("plate--empty");
    confDisplay.innerHTML = confBadge(data.best_confidence);
    const ms = data.processing_ms != null ? ` · ${data.processing_ms} ms` : "";
    setScanStatus("found", `Plate detected${ms}`);
    const best = (data.candidates || []).find((c) => c.plate === data.best_plate);
    showPlateBox(best?.box || (data.candidates?.[0]?.box ?? null));
  } else {
    plateDisplay.textContent = "—";
    plateDisplay.classList.add("plate--empty");
    confDisplay.innerHTML = "";
    hidePlateBox();
    setScanStatus("none", "No plate detected");
  }
}

function updateThrottleLabel() {
  throttleLabel.textContent = `Sent: ${framesSent} · Skipped: ${framesSkipped}`;
}

function updateFps() {
  const now = Date.now();
  const elapsed = (now - lastFpsTick) / 1000;
  if (elapsed >= 1) {
    const rate = (framesSent / elapsed).toFixed(1);
    fpsLabel.textContent = `Capture: ${rate}/s`;
    framesSent = 0;
    framesSkipped = 0;
    lastFpsTick = now;
    updateThrottleLabel();
  }
}

function captureFrame(force = false) {
  if (!cameraOn || !video.videoWidth) return false;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    connectWs();
    return false;
  }
  if (scanning) return false;
  if (!force) {
    // Auto interval handles pacing; manual scans use MIN_MANUAL_SCAN_MS below.
  } else if (Date.now() - lastManualScan < MIN_MANUAL_SCAN_MS) {
    return false;
  }

  let w = video.videoWidth;
  let h = video.videoHeight;
  if (w > MAX_FRAME_WIDTH) {
    h = Math.round((h * MAX_FRAME_WIDTH) / w);
    w = MAX_FRAME_WIDTH;
  }
  lastFullCaptureW = w;
  lastFullCaptureH = h;

  const roi = currentRoi;
  // Pad inside ROI so edge digits (e.g. leading "1") are not clipped at crop bounds.
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
  lastCaptureW = cropW;
  lastCaptureH = cropH;

  canvas.width = cropW;
  canvas.height = cropH;
  ctx.drawImage(video, cropX, cropY, cropW, cropH, 0, 0, cropW, cropH);

  canvas.toBlob(
    (blob) => {
      if (!blob || !cameraOn) return;
      blob.arrayBuffer().then((buf) => {
        if (ws && ws.readyState === WebSocket.OPEN && !scanning) {
          ws.send(buf);
          framesSent += 1;
          if (force) lastManualScan = Date.now();
        }
      });
    },
    "image/jpeg",
    JPEG_QUALITY
  );
  return true;
}

function cameraErrorMessage(err) {
  const name = err?.name || "";
  if (name === "NotAllowedError" || name === "PermissionDeniedError") {
    return "Camera permission denied";
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError") {
    return "No camera found";
  }
  if (name === "OverconstrainedError") {
    return "Camera unavailable or unplugged";
  }
  if (name === "NotReadableError") {
    return "Camera in use by another app";
  }
  if (location.protocol !== "https:" && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
    return "Camera requires HTTPS on this host";
  }
  return err?.message || "Camera unavailable";
}

function cameraLabel(device, index) {
  return device.label || `Camera ${index + 1}`;
}

async function refreshCameraList() {
  if (!navigator.mediaDevices?.enumerateDevices) {
    cameraSelect.innerHTML = '<option value="">Not supported</option>';
    cameraSelect.disabled = true;
    return;
  }

  let devices;
  try {
    devices = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
  } catch {
    cameraSelect.innerHTML = '<option value="">Unable to list cameras</option>';
    cameraSelect.disabled = true;
    return;
  }

  const previous = cameraSelect.value || selectedDeviceId;

  if (devices.length === 0) {
    cameraSelect.innerHTML = '<option value="">No cameras found</option>';
    cameraSelect.disabled = true;
    selectedDeviceId = "";
    return;
  }

  cameraSelect.disabled = false;
  cameraSelect.innerHTML = "";
  devices.forEach((device, index) => {
    const option = document.createElement("option");
    option.value = device.deviceId;
    option.textContent = cameraLabel(device, index);
    cameraSelect.appendChild(option);
  });

  const match = devices.find((d) => d.deviceId === previous);
  if (match) {
    cameraSelect.value = match.deviceId;
    selectedDeviceId = match.deviceId;
  } else {
    cameraSelect.value = devices[0].deviceId;
    selectedDeviceId = devices[0].deviceId;
  }
  if (!cameraOn) loadRoiForCurrentDevice();
}

function buildVideoConstraints(deviceId) {
  const video = { width: { ideal: 1280 }, height: { ideal: 720 } };
  if (deviceId) {
    video.deviceId = { exact: deviceId };
  } else {
    video.facingMode = "environment";
  }
  return { video, audio: false };
}

function attachStreamEndHandler(track) {
  track.addEventListener("ended", () => {
    if (cameraOn && !switchingCamera) {
      setScanStatus("error", "Camera disconnected");
      stopCamera();
      refreshCameraList();
    }
  });
}

async function acquireStream(deviceId) {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("getUserMedia not supported in this browser");
  }
  if (deviceId) {
    try {
      return await navigator.mediaDevices.getUserMedia(buildVideoConstraints(deviceId));
    } catch (err) {
      throw new Error(cameraErrorMessage(err));
    }
  }
  try {
    return await navigator.mediaDevices.getUserMedia(buildVideoConstraints(null));
  } catch (err) {
    try {
      return await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    } catch (err2) {
      throw new Error(cameraErrorMessage(err2));
    }
  }
}

async function openCameraStream(deviceId) {
  const newStream = await acquireStream(deviceId);
  const track = newStream.getVideoTracks()[0];
  if (track) attachStreamEndHandler(track);

  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
  }
  stream = newStream;
  video.srcObject = stream;
  return newStream;
}

async function switchCameraDevice(deviceId) {
  if (!cameraOn || switchingCamera || !deviceId) return;
  switchingCamera = true;
  selectedDeviceId = deviceId;
  try {
    await openCameraStream(deviceId);
    await refreshCameraList();
    loadRoiForCurrentDevice();
    hidePlateBox();
    setScanStatus("idle", "Ready");
  } catch (e) {
    setScanStatus("error", e.message || "Camera unavailable");
    stopCamera();
    await refreshCameraList();
  } finally {
    switchingCamera = false;
  }
}

async function startCamera() {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("getUserMedia not supported in this browser");
  }

  await refreshCameraList();
  selectedDeviceId = cameraSelect.value || selectedDeviceId;

  if (!selectedDeviceId && cameraSelect.options.length && cameraSelect.options[0].value) {
    selectedDeviceId = cameraSelect.options[0].value;
  }

  connectWs();
  try {
    await openCameraStream(selectedDeviceId || null);
  } catch (err) {
    throw err instanceof Error ? err : new Error(cameraErrorMessage(err));
  }
  await refreshCameraList();
  loadRoiForCurrentDevice();
  cameraOn = true;
  overlay.classList.add("video-overlay--hidden");
  setRoiLayerMode(true);
  video.addEventListener("loadedmetadata", updateRoiDisplay);
  toggleBtn.textContent = "Stop Camera";
  toggleBtn.classList.add("live-toggle--stop");
  scanBtn.disabled = false;
  setScanStatus("idle", "Ready");
  plateDisplay.textContent = "—";
  plateDisplay.classList.add("plate--empty");
  confDisplay.innerHTML = "";
  timeDisplay.textContent = "";
  hidePlateBox();

  lastFpsTick = Date.now();
  framesSent = 0;
  framesSkipped = 0;
  lastManualScan = 0;
  fpsTimer = setInterval(updateFps, 1000);
  captureTimer = setInterval(() => captureFrame(false), CAPTURE_INTERVAL_MS);
  updateRoiDisplay();
  captureFrame(false);
}

function stopCamera() {
  cameraOn = false;
  scanning = false;
  if (captureTimer) {
    clearInterval(captureTimer);
    captureTimer = null;
  }
  if (fpsTimer) {
    clearInterval(fpsTimer);
    fpsTimer = null;
  }
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  video.srcObject = null;
  video.removeEventListener("loadedmetadata", updateRoiDisplay);
  setRoiLayerMode(false);
  updateRoiDisplay();
  overlay.classList.remove("video-overlay--hidden");
  toggleBtn.textContent = "Start Camera";
  toggleBtn.classList.remove("live-toggle--stop");
  scanBtn.disabled = true;
  setScanStatus("off", "Camera off");
  plateDisplay.textContent = "—";
  plateDisplay.classList.add("plate--empty");
  confDisplay.innerHTML = "";
  timeDisplay.textContent = "";
  hidePlateBox();
  fpsLabel.textContent = "FPS: —";
  throttleLabel.textContent = "Interval: 2.0s";
  if (ws) {
    ws.close();
    ws = null;
  }
}

toggleBtn.addEventListener("click", () => {
  if (cameraOn) stopCamera();
  else startCamera().catch((e) => {
    setScanStatus("error", e.message || "Camera permission denied");
    refreshCameraList();
  });
});

cameraSelect.addEventListener("change", () => {
  const deviceId = cameraSelect.value;
  if (!deviceId) return;
  if (cameraOn) switchCameraDevice(deviceId);
  else {
    selectedDeviceId = deviceId;
    loadRoiForCurrentDevice();
  }
});

if (navigator.mediaDevices) {
  navigator.mediaDevices.addEventListener("devicechange", () => {
    refreshCameraList();
  });
}

roiBox.addEventListener("pointerdown", onRoiPointerDown);
roiBox.addEventListener("pointermove", onRoiPointerMove);
roiBox.addEventListener("pointerup", onRoiPointerUp);
roiBox.addEventListener("pointercancel", onRoiPointerUp);

roiPresetBtns.forEach((btn) => {
  btn.addEventListener("click", () => applyRoiPreset(btn.dataset.preset));
});

OcrAuth.requireKey().then(() => {
  refreshCameraList();
  setRoiLayerMode(false);
  updateRoiDisplay();
}).catch(() => {
  setScanStatus("error", "API key required");
});

scanBtn.addEventListener("click", () => {
  if (!cameraOn || scanning) return;
  captureFrame(true);
});

window.addEventListener("resize", () => {
  updateRoiDisplay();
  if (lastPlateBox) showPlateBox(lastPlateBox);
});

window.addEventListener("beforeunload", () => {
  stopCamera();
});
