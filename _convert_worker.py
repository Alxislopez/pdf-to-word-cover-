"""
_convert_worker.py
------------------
Child process spawned by app.py for each page-range chunk.

Usage:
    python _convert_worker.py <pdf_path> <docx_path> <start_page> <end_page>

    start_page : 0-based inclusive start
    end_page   : 0-based exclusive end  (same convention as pdf2docx)

Exit 0 = success. Non-zero = failure (error on stderr).
"""

import sys


def main():
    if len(sys.argv) != 5:
        print(
            "Usage: _convert_worker.py <pdf_path> <docx_path> <start> <end>",
            file=sys.stderr,
        )
        sys.exit(1)

    pdf_path  = sys.argv[1]
    docx_path = sys.argv[2]
    start     = int(sys.argv[3])
    end       = int(sys.argv[4])   # None-equivalent: pass total page count

    try:
        from pdf2docx import Converter
        cv = Converter(pdf_path)
        cv.convert(docx_path, start=start, end=end)
        cv.close()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
