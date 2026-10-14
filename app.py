"""
PDF to Word Converter — Flask Backend
Handles file upload, conversion via pdf2docx, and download.

Memory strategy: conversion is run in a separate subprocess so that
PyMuPDF / OpenCV memory is fully released back to the OS when the
child process exits — keeping the parent Gunicorn worker lean.
"""

import os
import sys
import uuid
import time
import subprocess
import threading
from pathlib import Path

from flask import Flask, request, jsonify, send_file, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder="static", static_url_path="")

# ── Configuration ──────────────────────────────────────────────────────────────
# Use /tmp on cloud (read-only root), or a local folder when running locally.
_base = Path("/tmp") if os.environ.get("RENDER") else Path(__file__).parent
UPLOAD_FOLDER = _base / "pdf_to_word_uploads"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf"}

# Free-tier Render has 512 MB RAM — keep individual files ≤ 15 MB.
MAX_MB = int(os.environ.get("MAX_UPLOAD_MB", 15))
MAX_CONTENT_LENGTH = MAX_MB * 1024 * 1024

app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH


# ── Helpers ────────────────────────────────────────────────────────────────────
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def cleanup_old_files(max_age_seconds: int = 600):
    """Delete temp files older than *max_age_seconds* (default 10 min)."""
    now = time.time()
    try:
        for f in UPLOAD_FOLDER.iterdir():
            if f.is_file() and (now - f.stat().st_mtime) > max_age_seconds:
                f.unlink(missing_ok=True)
    except Exception:
        pass


# Background cleanup thread — runs every 5 minutes
def _periodic_cleanup():
    while True:
        time.sleep(300)
        cleanup_old_files()

_cleanup_thread = threading.Thread(target=_periodic_cleanup, daemon=True)
_cleanup_thread.start()


# ── Subprocess conversion helper ───────────────────────────────────────────────
# Running pdf2docx in a child process means its entire memory footprint
# (PyMuPDF + OpenCV + NumPy) is freed when the child exits.  The parent
# Gunicorn worker never allocates that memory at all.
_CONVERTER_SCRIPT = Path(__file__).parent / "_convert_worker.py"


def convert_in_subprocess(pdf_path: str, docx_path: str, timeout: int = 110) -> str | None:
    """
    Convert *pdf_path* → *docx_path* in a fresh subprocess.
    Returns None on success, or an error string on failure.
    """
    result = subprocess.run(
        [sys.executable, str(_CONVERTER_SCRIPT), pdf_path, docx_path],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or "Unknown conversion error"
        return stderr
    return None


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/convert", methods=["POST"])
def convert_pdf():
    """Accept a PDF upload, convert it to .docx in a subprocess, return a token."""

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files["file"]

    if not file.filename:
        return jsonify({"error": "Empty filename."}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Only PDF files are accepted."}), 400

    # Build unique paths
    job_id = uuid.uuid4().hex[:12]
    original_stem = Path(secure_filename(file.filename)).stem or "document"
    pdf_path = UPLOAD_FOLDER / f"{job_id}_{original_stem}.pdf"
    docx_path = UPLOAD_FOLDER / f"{job_id}_{original_stem}.docx"

    file.save(str(pdf_path))

    # Convert in a subprocess — memory is freed when child exits
    try:
        error = convert_in_subprocess(str(pdf_path), str(docx_path))
    except subprocess.TimeoutExpired:
        pdf_path.unlink(missing_ok=True)
        return jsonify({"error": "Conversion timed out. Try a smaller file."}), 504
    except Exception as exc:
        pdf_path.unlink(missing_ok=True)
        return jsonify({"error": f"Conversion error: {exc}"}), 500
    finally:
        pdf_path.unlink(missing_ok=True)   # Always remove source PDF

    if error:
        docx_path.unlink(missing_ok=True)
        return jsonify({"error": f"Conversion failed: {error}"}), 500

    return jsonify({
        "token": job_id,
        "filename": f"{original_stem}.docx",
    })


@app.route("/download/<token>/<filename>")
def download_file(token, filename):
    """Serve the converted .docx file for direct browser download."""
    matches = list(UPLOAD_FOLDER.glob(f"{token}_*.docx"))
    if not matches:
        return jsonify({"error": "File not found or expired."}), 404

    docx_path = matches[0]
    return send_file(
        str(docx_path),
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ── Entry Point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
