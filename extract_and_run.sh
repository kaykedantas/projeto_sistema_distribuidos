#!/bin/bash
set -e
file="discovery.pdf"
if [ ! -f "$file" ]; then echo "MISSING_FILE"; exit 2; fi
out="/tmp/discovery_extraction.txt"
# Try pdftotext
if command -v pdftotext >/dev/null 2>&1; then
  echo "pdftotext found"
  pdftotext -layout -enc UTF-8 "$file" - | sed 's/\r$//' > "$out" || true
  echo "---EXTRACTED pdftotext START---"
  sed -n '1,400p' "$out" || true
  echo "---EXTRACTED pdftotext END---"
  exit 0
fi
# Try pdftoppm + tesseract
if command -v pdftoppm >/dev/null 2>&1 && command -v tesseract >/dev/null 2>&1; then
  echo "pdftoppm + tesseract found"
  tmpdir=$(mktemp -d)
  pdftoppm -png -r 300 "$file" "$tmpdir/page" || true
  for img in "$tmpdir"/page-*.png; do
    if [ -f "$img" ]; then
      echo "OCR $img"
      tesseract "$img" "$img" -l por+eng quiet 2>/dev/null || tesseract "$img" "$img" -l eng quiet 2>/dev/null || true
    fi
  done
  cat "$tmpdir"/page-*.png.txt > "$out" || true
  echo "---EXTRACTED OCR START---"
  sed -n '1,400p' "$out" || true
  echo "---EXTRACTED OCR END---"
  exit 0
fi
# Try magick/convert + tesseract
if (command -v magick >/dev/null 2>&1 || command -v convert >/dev/null 2>&1) && command -v tesseract >/dev/null 2>&1; then
  echo "ImageMagick + tesseract found"
  tmpdir=$(mktemp -d)
  if command -v magick >/dev/null 2>&1; then
    magick -density 300 "$file" "$tmpdir/page-%03d.png" || true
  else
    convert -density 300 "$file" "$tmpdir/page-%03d.png" || true
  fi
  for img in "$tmpdir"/page-*.png; do
    if [ -f "$img" ]; then
      echo "OCR $img"
      tesseract "$img" "$img" -l por+eng quiet 2>/dev/null || tesseract "$img" "$img" -l eng quiet 2>/dev/null || true
    fi
  done
  cat "$tmpdir"/page-*.png.txt > "$out" || true
  echo "---EXTRACTED OCR START---"
  sed -n '1,400p' "$out" || true
  echo "---EXTRACTED OCR END---"
  exit 0
fi
# Fallback: strings
if command -v strings >/dev/null 2>&1; then
  echo "Using strings fallback"
  strings "$file" | sed -n '1,400p' > "$out" || true
  sed -n '1,400p' "$out" || true
  exit 0
fi

echo "NO_TOOLS"
exit 3
