"""PDF helpers: render PDF pages to images for AI vision, and detect document types."""
import io
import sys
from pathlib import Path

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
PDF_EXT = {".pdf"}
DOC_EXT = IMAGE_EXT | PDF_EXT

MAX_PDF_PAGES_FOR_AI = 3


def is_pdf(path: str) -> bool:
    return Path(path).suffix.lower() in PDF_EXT


def pdf_to_images(pdf_path: str, max_pages: int = MAX_PDF_PAGES_FOR_AI,
                  dpi: int = 150) -> list[str]:
    """
    Render the first pages of a PDF to temporary PNG images (for the vision model).
    Requires PyMuPDF (pip install pymupdf) — pure wheel, works on Windows/Linux.
    """
    try:
        import pymupdf as fitz
    except ImportError:  # PyMuPDF < 1.24 style
        try:
            import fitz
        except ImportError as e:
            raise RuntimeError(
                "PDF support requires PyMuPDF. Install with: pip install pymupdf") from e

    out_paths: list[str] = []
    doc = fitz.open(pdf_path)
    try:
        n = min(len(doc), max_pages)
        if n == 0:
            raise RuntimeError("PDF has no pages")
        for i in range(n):
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=dpi)
            out = Path(pdf_path).with_name(f"__pdfpage_{i}_{Path(pdf_path).stem}.png")
            pix.save(str(out))
            out_paths.append(str(out))
    finally:
        doc.close()
    return out_paths


def vision_images(path: str) -> list[str]:
    """Return list of image paths to send to the vision model for any supported input."""
    if is_pdf(path):
        return pdf_to_images(path)
    return [path]


def cleanup_temp(images: list[str], original: str) -> None:
    """Remove generated page images (never the original)."""
    for p in images:
        if p != original and "__pdfpage_" in Path(p).name:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass
