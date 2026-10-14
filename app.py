"""
PDF to Word Converter — Flask Backend
Handles file upload, chunked conversion via pdf2docx, and download.

Memory strategy
───────────────
Large PDFs are split into 10-page chunks. Each chunk is converted by a
fresh subprocess (PyMuPDF + OpenCV + NumPy memory is fully released when
the child exits). The resulting chunk .docx files are then merged with
docxcompose and the chunks are deleted.

Peak RAM per subprocess ≈ 150–250 MB → safe on Render's 512 MB free tier
even for 50+ MB / 100+ page PDFs.
"""

import os
import sys
import uuid
import time
import subprocess
import threading
from pathlib import Path

import fitz                              # PyMuPDF — only used to count pages (lightweight)
from flask import Flask, request, jsonify, send_file, send_from_directory
from werkzeug.utils import secure_filename
from docx import Document as DocxDocument
from docxcompose.composer import Composer

app = Flask(__name__, static_folder="static", static_url_path="")

# ── Configuration ──────────────────────────────────────────────────────────────
# /tmp is the writable filesystem on Render; fall back to local folder.
_base = Path("/tmp") if os.environ.get("RENDER") else Path(__file__).parent
UPLOAD_FOLDER = _base / "pdf_to_word_uploads"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS  = {"pdf"}
CHUNK_SIZE          = 10                                   # pages per subprocess
MAX_MB              = int(os.environ.get("MAX_UPLOAD_MB", 50))   # raised back to 50 MB
MAX_CONTENT_LENGTH  = MAX_MB * 1024 * 1024

app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

_WORKER = Path(__file__).parent / "_convert_worker.py"


# ── Helpers ────────────────────────────────────────────────────────────────────
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_page_count(pdf_path: str) -> int:
    """Return the number of pages in the PDF (very low memory — reads only xref table)."""
    doc = fitz.open(pdf_path)
    count = len(doc)
    doc.close()
    return count


def convert_chunk(pdf_path: str, docx_path: str, start: int, end: int, timeout: int = 110) -> str | None:
    """
    Convert pages [start, end) of *pdf_path* into *docx_path* via a subprocess.
    Returns None on success, or an error string on failure.
    """
    result = subprocess.run(
        [sys.executable, str(_WORKER), pdf_path, docx_path, str(start), str(end)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        return result.stderr.strip() or "Unknown conversion error"
    return None


def merge_docx_files(chunk_paths: list[Path], output_path: Path) -> None:
    """
    Merge a list of .docx chunk files into a single output .docx using docxcompose.
    docxcompose properly handles styles, images, and relationships across chunks.
    """
    if len(chunk_paths) == 1:
        # Only one chunk — rename directly, no merge needed
        chunk_paths[0].rename(output_path)
        return

    master = DocxDocument(str(chunk_paths[0]))
    composer = Composer(master)

    for chunk_path in chunk_paths[1:]:
        doc = DocxDocument(str(chunk_path))
        composer.append(doc)

    composer.save(str(output_path))

    # Clean up individual chunk files
    for chunk_path in chunk_paths:
        chunk_path.unlink(missing_ok=True)


def cleanup_old_files(max_age_seconds: int = 600):
    """Delete temp files older than *max_age_seconds* (default 10 min)."""
    now = time.time()
    try:
        for f in UPLOAD_FOLDER.iterdir():
            if f.is_file() and (now - f.stat().st_mtime) > max_age_seconds:
                f.unlink(missing_ok=True)
    except Exception:
        pass


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
    """
    Upload a PDF, convert it in 10-page chunks (each in its own subprocess),
    merge the chunks, and return a download token.
    """

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files["file"]

    if not file.filename:
        return jsonify({"error": "Empty filename."}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Only PDF files are accepted."}), 400

    # ── Save uploaded PDF ──────────────────────────────────────────────
    job_id        = uuid.uuid4().hex[:12]
    original_stem = Path(secure_filename(file.filename)).stem or "document"
    pdf_path      = UPLOAD_FOLDER / f"{job_id}_{original_stem}.pdf"
    final_docx    = UPLOAD_FOLDER / f"{job_id}_{original_stem}.docx"

    file.save(str(pdf_path))

    # ── Count pages & build chunk ranges ──────────────────────────────
    try:
        total_pages = get_page_count(str(pdf_path))
    except Exception as exc:
        pdf_path.unlink(missing_ok=True)
        return jsonify({"error": f"Could not read PDF: {exc}"}), 400

    # Build list of (start, end) page ranges in CHUNK_SIZE increments
    ranges = [
        (start, min(start + CHUNK_SIZE, total_pages))
        for start in range(0, total_pages, CHUNK_SIZE)
    ]

    # ── Convert each chunk in its own subprocess ───────────────────────
    chunk_paths: list[Path] = []
    try:
        for i, (start, end) in enumerate(ranges):
            chunk_docx = UPLOAD_FOLDER / f"{job_id}_chunk{i:03d}.docx"
            error = convert_chunk(str(pdf_path), str(chunk_docx), start, end)

            if error:
                raise RuntimeError(f"Chunk {i} (pages {start}–{end}): {error}")

            chunk_paths.append(chunk_docx)

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Conversion timed out. Try a smaller file."}), 504

    except Exception as exc:
        return jsonify({"error": f"Conversion failed: {exc}"}), 500

    finally:
        # Always remove the source PDF immediately
        pdf_path.unlink(missing_ok=True)

        # If something went wrong mid-way, clean up any chunks produced so far
        if not final_docx.exists():
            for cp in chunk_paths:
                cp.unlink(missing_ok=True)

    # ── Merge chunks → final .docx ─────────────────────────────────────
    try:
        merge_docx_files(chunk_paths, final_docx)
    except Exception as exc:
        for cp in chunk_paths:
            cp.unlink(missing_ok=True)
        return jsonify({"error": f"Merge failed: {exc}"}), 500

    return jsonify({
        "token":    job_id,
        "filename": f"{original_stem}.docx",
        "pages":    total_pages,
        "chunks":   len(ranges),
    })


@app.route("/download/<token>/<filename>")
def download_file(token, filename):
    """Serve the merged .docx file for direct browser download."""
    matches = list(UPLOAD_FOLDER.glob(f"{token}_*.docx"))
    if not matches:
        return jsonify({"error": "File not found or expired."}), 404

    # Pick the final merged file (not any leftover chunks)
    docx_path = next(
        (p for p in matches if "chunk" not in p.name),
        matches[0]
    )

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
