"""
_convert_worker.py
------------------
Runs inside a child process spawned by app.py.
Converts a PDF to .docx using pdf2docx, then exits immediately so
all of PyMuPDF / OpenCV / NumPy memory is freed back to the OS.

Usage: python _convert_worker.py <pdf_path> <docx_path>
Exit code 0 = success, non-zero = failure (error written to stderr).
"""

import sys


def main():
    if len(sys.argv) != 3:
        print("Usage: _convert_worker.py <pdf_path> <docx_path>", file=sys.stderr)
        sys.exit(1)

    pdf_path, docx_path = sys.argv[1], sys.argv[2]

    try:
        from pdf2docx import Converter
        cv = Converter(pdf_path)
        cv.convert(docx_path, start=0, end=None)
        cv.close()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
