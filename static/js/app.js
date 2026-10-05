/**
 * AI Meeting Notes Generator — frontend
 */

(function () {
  "use strict";

  const API = {
    health: "/api/health",
    csrf: "/api/csrf-token",
    uploadAudio: "/api/upload-audio",
    processAudio: "/api/process-audio",
    submitTranscript: "/api/submit-transcript",
    status: "/api/status",
    cancel: "/api/cancel",
    copySummary: "/api/copy-summary",
    feedback: "/api/feedback",
  };

  const MAX_CHARS = 50000;
  let csrfToken = document.querySelector('input[name="csrf_token"]')?.value || "";

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    if (!container) return;
    const id = "toast-" + Date.now();
    const bg =
      type === "success" ? "text-bg-success" :
      type === "danger" ? "text-bg-danger" :
      type === "warning" ? "text-bg-warning" : "text-bg-primary";
    container.insertAdjacentHTML("beforeend", `
      <div id="${id}" class="toast toast-custom ${bg}" role="alert" aria-live="assertive">
        <div class="d-flex">
          <div class="toast-body">${escapeHtml(message)}</div>
          <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
      </div>`);
    const el = document.getElementById(id);
    new bootstrap.Toast(el, { delay: 4500 }).show();
    el.addEventListener("hidden.bs.toast", () => el.remove());
  }

  async function fetchCsrf() {
    try {
      const res = await fetch(API.csrf);
      const data = await res.json();
      if (data.csrf_token) csrfToken = data.csrf_token;
    } catch (_) {}
  }

  function apiHeaders(json = true) {
    const h = { "X-CSRFToken": csrfToken };
    if (json) h["Content-Type"] = "application/json";
    return h;
  }

  function initTheme() {
    const saved = localStorage.getItem("theme") || "dark";
    document.documentElement.setAttribute("data-theme", saved);
    const icon = document.getElementById("theme-icon");
    if (icon) icon.className = saved === "dark" ? "fa-solid fa-sun" : "fa-solid fa-moon";
    document.getElementById("theme-toggle")?.addEventListener("click", () => {
      const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem("theme", next);
      if (icon) icon.className = next === "dark" ? "fa-solid fa-sun" : "fa-solid fa-moon";
    });
  }

  async function checkApiStatus() {
    const badge = document.getElementById("api-status-badge");
    const text = document.getElementById("api-status-text");
    const spinner = document.getElementById("status-spinner");
    spinner?.classList.remove("d-none");
    try {
      const res = await fetch(API.health);
      const data = await res.json();
      spinner?.classList.add("d-none");
      if (text) {
        text.textContent = data.ready ? "Gemini ready" : "Setup needed";
        badge?.classList.toggle("status-ok", data.ready);
        badge?.classList.toggle("status-error", !data.ready);
      }
    } catch {
      spinner?.classList.add("d-none");
      if (text) text.textContent = "Offline";
    }
  }

  function initUpload() {
    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("audio-input");
    const browseBtn = document.getElementById("browse-btn");
    const fileNameEl = document.getElementById("selected-file-name");
    const submitBtn = document.getElementById("upload-submit-btn");
    const form = document.getElementById("audio-upload-form");
    if (!dropZone || !fileInput) return;

    function handleFile(file) {
      if (!file) return;
      const ext = file.name.split(".").pop()?.toLowerCase();
      if (!["mp3", "wav", "m4a"].includes(ext)) {
        showToast("Invalid file type. Use MP3, WAV, or M4A.", "danger");
        return;
      }
      if (file.size > 25 * 1024 * 1024) {
        showToast("File too large. Maximum size is 25 MB.", "danger");
        return;
      }
      const dt = new DataTransfer();
      dt.items.add(file);
      fileInput.files = dt.files;
      if (fileNameEl) fileNameEl.textContent = file.name;
      if (submitBtn) submitBtn.disabled = false;
    }

    browseBtn?.addEventListener("click", (e) => { e.stopPropagation(); fileInput.click(); });
    dropZone.addEventListener("click", () => fileInput.click());
    dropZone.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
    });
    fileInput.addEventListener("change", () => handleFile(fileInput.files[0]));
    ["dragenter", "dragover"].forEach((ev) => {
      dropZone.addEventListener(ev, (e) => { e.preventDefault(); dropZone.classList.add("drag-over"); });
    });
    ["dragleave", "drop"].forEach((ev) => {
      dropZone.addEventListener(ev, (e) => { e.preventDefault(); dropZone.classList.remove("drag-over"); });
    });
    dropZone.addEventListener("drop", (e) => handleFile(e.dataTransfer?.files?.[0]));

    form?.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!fileInput.files?.length) {
        showToast("Please select an audio file.", "warning");
        return;
      }
      submitBtn.disabled = true;
      submitBtn.textContent = "Uploading…";
      const formData = new FormData();
      formData.append("audio", fileInput.files[0]);
      formData.append("csrf_token", csrfToken);
      try {
        const res = await fetch(API.uploadAudio, {
          method: "POST",
          headers: { "X-CSRFToken": csrfToken },
          body: formData,
        });
        const data = await res.json();
        if (!res.ok) {
          showToast(data.error || "Upload failed", "danger");
          submitBtn.disabled = false;
          submitBtn.textContent = "Submit";
          return;
        }
        showToast("Upload complete. Processing…", "success");
        window.location.href = data.redirect || "/processing";
      } catch {
        showToast("Network error. Is the server running?", "danger");
        submitBtn.disabled = false;
        submitBtn.textContent = "Submit";
      }
    });
  }

  function initTranscriptCounter() {
    const textarea = document.getElementById("transcript-input");
    const counter = document.getElementById("char-counter");
    const form = document.getElementById("transcript-form");
    if (!textarea || !counter) return;

    function update() {
      const len = textarea.value.length;
      counter.textContent = `${len} / ${MAX_CHARS}`;
      counter.classList.toggle("warning", len > 0 && len < 50);
      counter.classList.toggle("error", len > MAX_CHARS);
    }
    textarea.addEventListener("input", update);
    update();

    form?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = textarea.value.trim();
      if (text.length < 50) {
        showToast(`Please enter at least 50 characters.`, "warning");
        return;
      }
      const btn = document.getElementById("transcript-submit-btn");
      btn.disabled = true;
      btn.textContent = "Processing…";
      try {
        const res = await fetch(API.submitTranscript, {
          method: "POST",
          headers: apiHeaders(),
          body: JSON.stringify({ transcript: text }),
        });
        const data = await res.json();
        if (!res.ok) {
          showToast(data.error || "Failed to generate summary", "danger");
          btn.disabled = false;
          btn.textContent = "Submit";
          return;
        }
        showToast("Summary generated!", "success");
        window.location.href = data.redirect || "/results";
      } catch {
        showToast("Network error. Please try again.", "danger");
        btn.disabled = false;
        btn.textContent = "Submit";
      }
    });
  }

  function initProcessing() {
    if (window.PROCESSING_MODE !== "audio") return;

    const progressBar = document.getElementById("progress-bar");
    const progressWrap = document.getElementById("progress-bar-wrap");
    const percentEl = document.getElementById("progress-percent");
    const messageEl = document.getElementById("processing-message");
    const errorEl = document.getElementById("processing-error");
    const cancelBtn = document.getElementById("cancel-btn");
    const backBtn = document.getElementById("back-home-btn");
    const stepPercents = { 1: 20, 2: 45, 3: 75, 4: 100 };

    function setStepUI(step) {
      const pct = stepPercents[step] || 15;
      if (progressBar) progressBar.style.width = `${pct}%`;
      if (progressWrap) progressWrap.setAttribute("aria-valuenow", String(pct));
      if (percentEl) percentEl.textContent = `${pct}%`;

      document.querySelectorAll(".stepper-item").forEach((el) => {
        const s = parseInt(el.dataset.step, 10);
        const badge = el.querySelector(".stepper-badge");
        const icon = el.querySelector(".stepper-icon");
        el.classList.remove("step-done", "step-active", "step-pending");

        if (s < step) {
          el.classList.add("step-done");
          if (badge) { badge.textContent = `STEP ${s} COMPLETE`; badge.className = "stepper-badge step-badge-done"; }
          if (icon) { icon.className = "stepper-icon step-icon-done"; icon.innerHTML = '<i class="fa-solid fa-check"></i>'; }
        } else if (s === step) {
          el.classList.add("step-active");
          if (badge) { badge.textContent = `STEP ${s} ACTIVE`; badge.className = "stepper-badge step-badge-active"; }
          if (icon) {
            icon.className = "stepper-icon step-icon-active";
            icon.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
          }
        } else {
          el.classList.add("step-pending");
          if (badge) { badge.textContent = `STEP ${s} PENDING`; badge.className = "stepper-badge step-badge-pending"; }
          if (icon) { icon.className = "stepper-icon step-icon-pending"; icon.innerHTML = ""; }
        }
      });
    }

    async function runProcessing() {
      setStepUI(2);
      if (messageEl) messageEl.textContent = "Processing your meeting file...";

      try {
        const res = await fetch(API.processAudio, { method: "POST", headers: apiHeaders() });
        const data = await res.json();
        if (data.cancelled) {
          if (messageEl) messageEl.textContent = "Cancelled.";
          backBtn?.classList.remove("d-none");
          return;
        }
        if (!res.ok) {
          if (errorEl) {
            errorEl.textContent = data.error + (data.hint ? ` — ${data.hint}` : "");
            errorEl.classList.remove("d-none");
          }
          showToast(data.error || "Processing failed", "danger");
          backBtn?.classList.remove("d-none");
          cancelBtn.disabled = true;
          return;
        }
        setStepUI(4);
        if (messageEl) messageEl.textContent = "Complete! Redirecting…";
        showToast("Summary ready!", "success");
        window.location.href = data.redirect || "/results";
      } catch {
        if (errorEl) {
          errorEl.textContent = "Network error. Check your connection and try again.";
          errorEl.classList.remove("d-none");
        }
        showToast("Network error.", "danger");
        backBtn?.classList.remove("d-none");
      }
    }

    const poll = setInterval(async () => {
      try {
        const res = await fetch(API.status);
        const job = await res.json();
        if (job.step >= 3) setStepUI(3);
        else if (job.step >= 2) setStepUI(2);
        else if (job.step >= 1) setStepUI(1);
        if (job.message && messageEl) messageEl.textContent = job.message;
      } catch (_) {}
    }, 1500);

    cancelBtn?.addEventListener("click", async () => {
      await fetch(API.cancel, { method: "POST", headers: apiHeaders() });
      clearInterval(poll);
      showToast("Processing cancelled.", "warning");
      window.location.href = "/";
    });

    setStepUI(1);
    runProcessing().finally(() => clearInterval(poll));
  }

  async function submitReview(rating, comment) {
    const res = await fetch(API.feedback, {
      method: "POST",
      headers: apiHeaders(),
      body: JSON.stringify({ rating, comment }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Review failed");
    return data;
  }

  function markFeedbackDone() {
    document.getElementById("star-rating")?.classList.add("d-none");
    document.getElementById("review-comment")?.classList.add("d-none");
    document.getElementById("review-submit-btn")?.classList.add("d-none");
    document.getElementById("feedback-thanks")?.classList.remove("d-none");
  }

  function initStarRating() {
    const stars = [...document.querySelectorAll(".star-btn")];
    const submitBtn = document.getElementById("review-submit-btn");
    if (!stars.length || !submitBtn) return;
    let selectedRating = 0;

    function paint(value) {
      stars.forEach((star) => star.classList.toggle("active", Number(star.dataset.value) <= value));
    }

    stars.forEach((star) => {
      star.addEventListener("mouseenter", () => paint(Number(star.dataset.value)));
      star.addEventListener("mouseleave", () => paint(selectedRating));
      star.addEventListener("click", () => {
        selectedRating = Number(star.dataset.value);
        paint(selectedRating);
        submitBtn.disabled = false;
      });
    });

    submitBtn.addEventListener("click", async () => {
      if (!selectedRating) return;
      const comment = document.getElementById("review-comment")?.value || "";
      submitBtn.disabled = true;
      try {
        await submitReview(selectedRating, comment);
        markFeedbackDone();
        showToast("Thanks for your review!", "success");
      } catch {
        showToast("Could not submit review.", "danger");
        submitBtn.disabled = false;
      }
    });
  }

  function initResults() {
    document.getElementById("copy-full-summary")?.addEventListener("click", async () => {
      try {
        const res = await fetch(API.copySummary);
        const data = await res.json();
        if (data.text) {
          await navigator.clipboard.writeText(data.text);
          showToast("Full summary copied!", "success");
        }
      } catch {
        showToast("Copy failed.", "danger");
      }
    });

    document.getElementById("share-summary")?.addEventListener("click", async () => {
      try {
        const res = await fetch(API.copySummary);
        const data = await res.json();
        if (navigator.share && data.text) {
          await navigator.share({ title: "Meeting Summary", text: data.text });
        } else if (data.text) {
          await navigator.clipboard.writeText(data.text);
          showToast("Copied for sharing!", "success");
        }
      } catch {
        showToast("Share not available.", "warning");
      }
    });

    document.querySelectorAll(".btn-copy-section").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const el = document.getElementById(btn.dataset.copyTarget);
        if (!el) return;
        let text = "";
        if (el.tagName === "UL" || el.tagName === "OL") {
          text = [...el.querySelectorAll("li")].map((li) => `• ${li.textContent.trim()}`).join("\n");
        } else {
          text = el.textContent.trim();
        }
        try {
          await navigator.clipboard.writeText(text);
          showToast("Section copied!", "success");
        } catch {
          showToast("Copy failed.", "danger");
        }
      });
    });

    initStarRating();

    const sections = document.querySelectorAll(".summary-block[id]");
    const links = document.querySelectorAll(".contents-link[href^='#']");
    if (sections.length && links.length) {
      const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            links.forEach((l) => l.classList.remove("active"));
            document.querySelector(`.contents-link[href="#${entry.target.id}"]`)?.classList.add("active");
          }
        });
      }, { rootMargin: "-15% 0px -55% 0px" });
      sections.forEach((s) => observer.observe(s));
    }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    initTheme();
    await fetchCsrf();
    checkApiStatus();
    setInterval(checkApiStatus, 60000);
    initUpload();
    initTranscriptCounter();
    initProcessing();
    initResults();
  });
})();
