"""PDF creation and archive file operations."""
import img2pdf
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from . import config

ILLEGAL = r'[<>:"/\\|?*\x00-\x1f]'
FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_[\w\-\u0600-\u06FF]+\.pdf$", re.UNICODE)


def sanitize_component(name: str) -> str:
    name = re.sub(ILLEGAL, "_", name).strip(" .")
    name = re.sub(r"\s+", "_", name)
    return name or "document"


def normalize_filename(name: str) -> str:
    name = sanitize_component(name)
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    if not FILENAME_RE.match(name):
        today = datetime.now().strftime("%Y-%m-%d")
        stem = os.path.splitext(name)[0]
        # ensure a date prefix exists
        if not re.match(r"^\d{4}-\d{2}-\d{2}_", stem):
            stem = f"{today}_{stem}"
        name = sanitize_component(stem) + ".pdf"
    return name


def resolve_dir(archive_root: str, target_dir: str, create: bool) -> Path:
    root = Path(archive_root).resolve()
    t = Path(target_dir)
    if t.is_absolute():
        p = t.resolve()
    else:
        p = (root / target_dir).resolve()
    # Security: must stay inside archive root
    if root != p and root not in p.parents:
        raise ValueError(f"Target directory escapes the archive root: {p}")
    if not p.exists():
        if not create:
            raise FileNotFoundError(f"Target folder does not exist: {p}")
        p.mkdir(parents=True, exist_ok=True)
    if not p.is_dir():
        raise NotADirectoryError(str(p))
    return p


def image_to_pdf(image_path: str, out_pdf: Path) -> Path:
    """High-quality lossless-in-JPEG image -> PDF. Auto-orients via EXIF."""
    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img)
    # Flatten to RGB for JPEG inside PDF
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    tmp = out_pdf.with_suffix(".jpg.tmp")
    img.save(tmp, "JPEG", quality=92, optimize=True)
    with open(out_pdf, "wb") as f:
        f.write(img2pdf.convert(str(tmp)))
    tmp.unlink(missing_ok=True)
    return out_pdf


def document_to_pdf(src_path: str, out_pdf: Path) -> Path:
    """Convert an image to PDF; for an existing PDF, keep the original file as-is."""
    if Path(src_path).suffix.lower() == ".pdf":
        shutil.copy2(src_path, out_pdf)
        return out_pdf
    return image_to_pdf(src_path, out_pdf)


def unique_path(directory: Path, filename: str) -> Path:
    p = directory / filename
    if not p.exists():
        return p
    stem, ext = os.path.splitext(filename)
    for i in range(2, 1000):
        cand = directory / f"{stem}_{i}{ext}"
        if not cand.exists():
            return cand
    return directory / f"{stem}_{int(time.time())}{ext}"


def save_to_archive(image_path: str, target_dir: str, filename: str,
                    create_folder: bool = False) -> dict:
    """The 'save_pdf_to_archive' tool implementation. Returns info about the saved PDF."""
    archive_root = config.get("archive_root")
    directory = resolve_dir(archive_root, target_dir, create_folder)
    fname = normalize_filename(filename)
    out = unique_path(directory, fname)
    document_to_pdf(image_path, out)
    return {
        "saved_path": str(out),
        "relative_path": str(out.relative_to(Path(archive_root).resolve())),
        "folder": str(directory),
        "filename": out.name,
        "created_folder": directory.name == sanitize_component(Path(target_dir).name) and create_folder,
        "size": out.stat().st_size,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


# ---------------- Activity log ----------------

def load_activity() -> list[dict]:
    import json
    p = config.ACTIVITY_LOG_PATH
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def log_activity(entry: dict) -> list[dict]:
    import json
    entries = load_activity()
    entries.insert(0, entry)
    limit = int(config.get("recent_limit", 50))
    entries = entries[:limit]
    config.ACTIVITY_LOG_PATH.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    return entries
