"""
PDF to Word Converter — Flask Backend
Handles file upload, conversion via pdf2docx, and download.
"""

import os
import uuid
import time
import threading
from pathlib import Path

from flask import Flask, request, jsonify, send_file, send_from_directory
from pdf2docx import Converter
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder="static", static_url_path="")

# ── Configuration ──────────────────────────────────────────────────────────────
UPLOAD_FOLDER = Path(__file__).parent / "temp_uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf"}
MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB limit

app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH


# ── Helpers ────────────────────────────────────────────────────────────────────
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def cleanup_old_files(max_age_seconds: int = 600):
    """Delete temp files older than *max_age_seconds* (default 10 min)."""
    now = time.time()
    for f in UPLOAD_FOLDER.iterdir():
        if f.is_file() and (now - f.stat().st_mtime) > max_age_seconds:
            f.unlink(missing_ok=True)


# Run cleanup every 5 minutes in a background thread
def _periodic_cleanup():
    while True:
        time.sleep(300)
        cleanup_old_files()

_cleanup_thread = threading.Thread(target=_periodic_cleanup, daemon=True)
_cleanup_thread.start()


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/convert", methods=["POST"])
def convert_pdf():
    """Accept a PDF upload, convert it to .docx, and return a download token."""

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files["file"]

    if file.filename == "" or not file.filename:
        return jsonify({"error": "Empty filename."}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Only PDF files are accepted."}), 400

    # Save uploaded PDF with a unique name
    job_id = uuid.uuid4().hex[:12]
    original_stem = Path(secure_filename(file.filename)).stem or "document"
    pdf_path = UPLOAD_FOLDER / f"{job_id}_{original_stem}.pdf"
    docx_path = UPLOAD_FOLDER / f"{job_id}_{original_stem}.docx"

    file.save(str(pdf_path))

    try:
        # Convert
        cv = Converter(str(pdf_path))
        cv.convert(str(docx_path), start=0, end=None)
        cv.close()
    except Exception as exc:
        # Clean up on failure
        pdf_path.unlink(missing_ok=True)
        docx_path.unlink(missing_ok=True)
        return jsonify({"error": f"Conversion failed: {exc}"}), 500

    # Clean up PDF immediately; the docx will be cleaned by the periodic task
    pdf_path.unlink(missing_ok=True)

    # Return a token so the client can download via a direct browser navigation
    return jsonify({
        "token": job_id,
        "filename": f"{original_stem}.docx",
    })


@app.route("/download/<token>/<filename>")
def download_file(token, filename):
    """Serve the converted .docx file for direct browser download."""

    # Find the matching file in the upload folder
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
    app.run(debug=True, port=5000)
