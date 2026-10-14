/* ═══════════════════════════════════════════════════════════════════════
   DocShift – Frontend Logic
   Handles drag-and-drop, file selection, upload + conversion, and
   UI state transitions.
   ═══════════════════════════════════════════════════════════════════════ */

(() => {
  "use strict";

  // ── DOM References ────────────────────────────────────────────────────
  const dropZone        = document.getElementById("drop-zone");
  const dropContent     = document.getElementById("drop-zone-content");
  const fileSelected    = document.getElementById("file-selected");
  const fileInput       = document.getElementById("file-input");
  const fileNameEl      = document.getElementById("file-name");
  const fileSizeEl      = document.getElementById("file-size");
  const btnRemove       = document.getElementById("btn-remove");
  const btnConvert      = document.getElementById("btn-convert");
  const progressSection = document.getElementById("progress-section");
  const progressBar     = document.getElementById("progress-bar");
  const progressText    = document.getElementById("progress-text");
  const successSection  = document.getElementById("success-section");
  const errorSection    = document.getElementById("error-section");
  const errorText       = document.getElementById("error-text");
  const btnNew          = document.getElementById("btn-new");
  const btnRetry        = document.getElementById("btn-retry");

  let selectedFile = null;

  // ── Helpers ───────────────────────────────────────────────────────────
  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function showSection(section) {
    [dropZone, btnConvert, progressSection, successSection, errorSection].forEach(
      (el) => el.classList.add("hidden")
    );
    if (section === "upload") {
      dropZone.classList.remove("hidden");
      btnConvert.classList.remove("hidden");
    } else if (section === "progress") {
      progressSection.classList.remove("hidden");
    } else if (section === "success") {
      successSection.classList.remove("hidden");
    } else if (section === "error") {
      errorSection.classList.remove("hidden");
    }
  }

  function setFile(file) {
    if (!file || file.type !== "application/pdf") {
      alert("Please select a valid PDF file.");
      return;
    }
    if (file.size > 15 * 1024 * 1024) {
      alert("File exceeds the 15 MB limit. Please use a smaller PDF.");
      return;
    }
    selectedFile = file;
    fileNameEl.textContent = file.name;
    fileSizeEl.textContent = formatBytes(file.size);
    dropContent.classList.add("hidden");
    fileSelected.classList.remove("hidden");
    btnConvert.disabled = false;
  }

  function clearFile() {
    selectedFile = null;
    fileInput.value = "";
    dropContent.classList.remove("hidden");
    fileSelected.classList.add("hidden");
    btnConvert.disabled = true;
  }

  // ── Drag & Drop ──────────────────────────────────────────────────────
  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("drag-over");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("drag-over");
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    const file = e.dataTransfer.files[0];
    if (file) setFile(file);
  });

  // ── Click / Keyboard to browse ──────────────────────────────────────
  dropZone.addEventListener("click", () => fileInput.click());
  dropZone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) setFile(fileInput.files[0]);
  });

  // ── Remove file ─────────────────────────────────────────────────────
  btnRemove.addEventListener("click", (e) => {
    e.stopPropagation();
    clearFile();
  });

  // ── Convert ─────────────────────────────────────────────────────────
  btnConvert.addEventListener("click", async () => {
    if (!selectedFile) return;

    showSection("progress");
    progressBar.style.width = "0%";
    progressText.textContent = "Uploading…";

    const formData = new FormData();
    formData.append("file", selectedFile);

    // Simulate smooth progress while waiting for the server
    let progress = 0;
    const tick = setInterval(() => {
      if (progress < 85) {
        progress += Math.random() * 8 + 2;
        if (progress > 85) progress = 85;
        progressBar.style.width = progress + "%";
      }
      if (progress >= 30) {
        progressText.textContent = "Converting…";
      }
    }, 400);

    try {
      const response = await fetch("/convert", {
        method: "POST",
        body: formData,
      });

      clearInterval(tick);

      if (!response.ok) {
        let msg = "Conversion failed.";
        try {
          const json = await response.json();
          if (json.error) msg = json.error;
        } catch (_) {}
        throw new Error(msg);
      }

      // Finish the progress bar
      progressBar.style.width = "100%";
      progressText.textContent = "Done!";

      // Parse the download token from JSON response
      const data = await response.json();

      // Trigger download via direct browser navigation (ensures correct filename)
      const downloadUrl = `/download/${data.token}/${encodeURIComponent(data.filename)}`;
      const a = document.createElement("a");
      a.href = downloadUrl;
      a.download = data.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();

      // Show success after a brief moment
      setTimeout(() => showSection("success"), 600);
    } catch (err) {
      clearInterval(tick);
      errorText.textContent = err.message || "Something went wrong.";
      showSection("error");
    }
  });

  // ── Reset buttons ───────────────────────────────────────────────────
  btnNew.addEventListener("click", () => {
    clearFile();
    showSection("upload");
  });

  btnRetry.addEventListener("click", () => {
    clearFile();
    showSection("upload");
  });
})();
