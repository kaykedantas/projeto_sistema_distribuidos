import sys
from pathlib import Path


def ensure_pypdf():
    try:
        import pypdf
    except Exception:
        import subprocess, sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pypdf"])
        import pypdf
    return pypdf


def extract_text(pdf_path):
    ensure_pypdf()
    from pypdf import PdfReader
    reader = PdfReader(pdf_path)
    text_parts = []
    for page in reader.pages:
        try:
            text = page.extract_text()
        except Exception:
            text = ""
        if text:
            text_parts.append(text)
    return "\n\n".join(text_parts)


def main():
    if len(sys.argv) < 2:
        print("Usage: python extract_pdf_text.py file.pdf", file=sys.stderr)
        sys.exit(1)
    pdf_path = sys.argv[1]
    if not Path(pdf_path).exists():
        print(f"File not found: {pdf_path}", file=sys.stderr)
        sys.exit(2)
    out = extract_text(pdf_path)
    print(out)


if __name__ == "__main__":
    main()
