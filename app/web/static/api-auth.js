"use strict";

/** Browser-side API key gate and authenticated fetch helpers. */
(function () {
  const STORAGE_KEY = "ocr-api-key";

  function getKey() {
    return sessionStorage.getItem(STORAGE_KEY) || "";
  }

  function setKey(key) {
    sessionStorage.setItem(STORAGE_KEY, key);
  }

  function clearKey() {
    sessionStorage.removeItem(STORAGE_KEY);
  }

  function authHeaders() {
    const key = getKey();
    return key ? { "X-API-Key": key } : {};
  }

  function authFetch(url, options) {
    const opts = options || {};
    const headers = Object.assign({}, opts.headers || {}, authHeaders());
    return fetch(url, Object.assign({}, opts, { headers }));
  }

  function wsUrl(path) {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const key = getKey();
    const base = `${proto}//${location.host}${path}`;
    if (!key) return base;
    return `${base}?api_key=${encodeURIComponent(key)}`;
  }

  function ensureModal() {
    let modal = document.getElementById("api-key-modal");
    if (modal) return modal;

    modal = document.createElement("div");
    modal.id = "api-key-modal";
    modal.className = "api-key-modal";
    modal.innerHTML = `
      <div class="api-key-modal__card" role="dialog" aria-labelledby="api-key-title" aria-modal="true">
        <h2 id="api-key-title">API key required</h2>
        <p class="muted">Enter the server API key to use OCR, ANPR, and KYC features.</p>
        <form id="api-key-form">
          <label for="api-key-input">API key</label>
          <input id="api-key-input" type="password" autocomplete="off" placeholder="Paste your API key" required />
          <p id="api-key-error" class="api-key-modal__error" hidden></p>
          <button type="submit" class="run">Continue</button>
        </form>
      </div>`;
    document.body.appendChild(modal);
    return modal;
  }

  function showError(message) {
    const el = document.getElementById("api-key-error");
    if (!el) return;
    if (message) {
      el.textContent = message;
      el.hidden = false;
    } else {
      el.textContent = "";
      el.hidden = true;
    }
  }

  async function authRequired() {
    const res = await fetch("/api/health");
    return res.status === 401;
  }

  async function validateKey(key) {
    const res = await fetch("/api/health", {
      headers: { "X-API-Key": key },
    });
    if (res.status === 401) {
      throw new Error("Invalid API key.");
    }
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Could not verify API key.");
    }
    return true;
  }

  async function requireKey() {
    const needed = await authRequired();
    if (!needed) {
      return getKey();
    }

    const existing = getKey();
    if (existing) {
      return existing;
    }

    const modal = ensureModal();
    modal.classList.add("api-key-modal--open");
    const input = document.getElementById("api-key-input");
    const form = document.getElementById("api-key-form");
    input.value = "";
    showError("");
    input.focus();

    return new Promise((resolve) => {
      form.onsubmit = async (ev) => {
        ev.preventDefault();
        const key = input.value.trim();
        if (!key) {
          showError("API key is required.");
          return;
        }
        const btn = form.querySelector('button[type="submit"]');
        btn.disabled = true;
        showError("");
        try {
          await validateKey(key);
          setKey(key);
          modal.classList.remove("api-key-modal--open");
          resolve(key);
        } catch (err) {
          showError(err.message || "Invalid API key.");
        } finally {
          btn.disabled = false;
        }
      };
    });
  }

  window.OcrAuth = {
    getKey,
    setKey,
    clearKey,
    authHeaders,
    authFetch,
    wsUrl,
    requireKey,
  };
})();
