"""Smart Archive — local AI document archiving server (FastAPI + Ollama gemma4:e2b)."""
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Body
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, tree_scanner, archiver, ollama_client, capture, pdf_utils

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "uploads"
UPLOADS.mkdir(exist_ok=True)

app = FastAPI(title="Smart Archive", version="1.0.0")

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".pdf"}


def get_tree() -> dict:
    root = config.get("archive_root")
    Path(root).mkdir(parents=True, exist_ok=True)
    return tree_scanner.build_tree(root, int(config.get("max_tree_depth", 6)))


# ---------------- Settings & config ----------------

class SettingsModel(BaseModel):
    archive_root: str | None = None
    ollama_url: str | None = None
    model: str | None = None
    mode: str | None = None          # "review" | "auto"
    language_hint: str | None = None
    max_tree_depth: int | None = None


@app.get("/api/settings")
def read_settings():
    return {"settings": config.all_settings(),
            "ollama": ollama_client.is_available(),
            "scanner": {"scanimage": capture.scanner_available(),
                        "devices": capture.list_scanners(),
                        "webcam": capture.webcam_available()}}


@app.put("/api/settings")
def write_settings(body: SettingsModel):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    if "archive_root" in data:
        p = Path(data["archive_root"]).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        data["archive_root"] = str(p.resolve())
    return {"settings": config.update(**data)}


# ---------------- Archive tree ----------------

@app.get("/api/tree")
def archive_tree():
    return {"root": config.get("archive_root"), "tree": get_tree()}


@app.post("/api/tree/refresh")
def refresh_tree():
    return archive_tree()


@app.post("/api/folders/create")
def create_folder(body: dict = Body(...)):
    parent = body.get("parent", "")
    name = archiver.sanitize_component(body.get("name", "New Folder"))
    root = Path(config.get("archive_root")).resolve()
    base = (root / parent).resolve() if parent else root
    if root not in base.parents and base != root:
        raise HTTPException(400, "parent outside archive root")
    target = base / name
    i = 2
    while target.exists():
        target = base / f"{name}_{i}"
        i += 1
    target.mkdir(parents=True)
    return {"path": str(target), "tree": get_tree()}


# ---------------- Upload / capture ----------------

def _store_upload(data: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower() or ".png"
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Unsupported file type: {ext}")
    path = UPLOADS / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(data)
    return str(path)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    path = _store_upload(data, file.filename or "upload.png")
    return {"path": path, "name": Path(path).name, "size": len(data)}


@app.post("/api/capture/scan")
def capture_scan(body: dict = Body(default={})):
    try:
        path = capture.scan_to_image(body.get("device"), int(body.get("dpi", 300)))
        return {"path": path, "name": Path(path).name, "size": Path(path).stat().st_size}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/capture/webcam")
def capture_webcam(body: dict = Body(default={})):
    try:
        path = capture.webcam_snapshot(int(body.get("camera", 0)))
        return {"path": path, "name": Path(path).name, "size": Path(path).stat().st_size}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/browse")
def browse_dirs(path: str = ""):
    """List subdirectories of a path for the in-app folder picker."""
    root = Path(config.get("archive_root")).resolve()
    p = Path(path).expanduser().resolve() if path else Path.home()
    if not p.is_dir():
        raise HTTPException(400, f"Not a directory: {p}")
    dirs = []
    try:
        for e in sorted(p.iterdir(), key=lambda x: x.name.lower()):
            if e.is_dir() and not e.name.startswith("."):
                dirs.append({"name": e.name, "path": str(e)})
    except OSError as e:
        raise HTTPException(500, str(e))
    parent = str(p.parent) if p.parent != p else None
    return {"current": str(p), "parent": parent, "dirs": dirs,
            "is_inside_archive": root == p or root in p.parents}


@app.get("/api/file")
def get_file(path: str):
    p = Path(path).resolve()
    allowed = {UPLOADS.resolve(), Path(config.get("archive_root")).resolve()}
    if not any(p == a or a in p.parents for a in allowed):
        raise HTTPException(403, "Path not allowed")
    if not p.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(p)


# ---------------- AI analysis ----------------

def _tree_summary() -> str:
    tree = get_tree()
    return "\n".join(tree_scanner.compact_summary(tree))


@app.post("/api/analyze")
def analyze(body: dict = Body(...)):
    image_path = body.get("path")
    if not image_path or not Path(image_path).is_file():
        raise HTTPException(400, "Provide a valid uploaded image path")

    ok, msg = ollama_client.is_available()
    if not ok:
        raise HTTPException(503, msg)

    pages = pdf_utils.vision_images(image_path)
    try:
        plan = ollama_client.analyze_document(
            pages, _tree_summary(), datetime.now().strftime("%Y-%m-%d"))
    finally:
        pdf_utils.cleanup_temp(pages, image_path)
    plan.pop("_raw", None)

    # Validate + enrich
    root = Path(config.get("archive_root")).resolve()
    target = plan.get("target_dir") or ""
    try:
        exists = archiver.resolve_dir(str(root), target, create=False) is not None
    except Exception:
        exists = False
    plan["target_dir_exists"] = exists
    plan["mode"] = config.get("mode")
    plan["suggestions"] = [d for d in tree_scanner.flatten_dirs(get_tree())
                           if str(root) in d][:80]
    return {"plan": plan}


@app.post("/api/archive")
def archive_document(body: dict = Body(...)):
    """
    Execute the filing: create PDF from image, save into target folder, log activity.
    body: {path, target_dir, filename, create_folder, meta}
    """
    image_path = body.get("path")
    if not image_path or not Path(image_path).is_file():
        raise HTTPException(400, "Provide a valid uploaded image path")

    ok, msg = ollama_client.is_available()
    status_ok = ok  # we can still archive without Ollama if the user gave explicit values
    target_dir = body.get("target_dir")
    filename = body.get("filename")
    if not target_dir or not filename:
        raise HTTPException(400, "target_dir and filename are required")

    t0 = time.time()
    try:
        result = archiver.save_to_archive(
            image_path, target_dir, filename,
            bool(body.get("create_folder", False)))
    except Exception as e:
        raise HTTPException(500, f"Archive failed: {e}")

    meta = body.get("meta") or {}
    entry = {
        "id": uuid.uuid4().hex[:10],
        "timestamp": result["timestamp"],
        "source_image": image_path,
        "saved_path": result["saved_path"],
        "folder": result["folder"],
        "filename": result["filename"],
        "size": result["size"],
        "title": meta.get("title", ""),
        "doc_type": meta.get("doc_type", ""),
        "summary_ar": meta.get("summary_ar", ""),
        "summary_en": meta.get("summary_en", ""),
        "duration_s": round(time.time() - t0, 1),
        "model": config.get("model"),
        "ai_confirmed": status_ok,
    }
    entries = archiver.log_activity(entry)
    return {"result": result, "entry": entry, "activity": entries}


@app.post("/api/tool-call")
def tool_call(body: dict = Body(...)):
    """Optional second stage: let Gemma confirm the filing via native tool calling."""
    image_path = body.get("path")
    if not image_path or not Path(image_path).is_file():
        raise HTTPException(400, "Provide a valid uploaded image path")
    pages = pdf_utils.vision_images(image_path)
    try:
        plan = ollama_client.confirm_with_tool(
            pages, _tree_summary(), datetime.now().strftime("%Y-%m-%d"))
    finally:
        pdf_utils.cleanup_temp(pages, image_path)
    return plan


# ---------------- Activity ----------------

@app.get("/api/activity")
def activity():
    return {"activity": archiver.load_activity()}


@app.delete("/api/activity")
def clear_activity():
    config.ACTIVITY_LOG_PATH.write_text("[]", encoding="utf-8")
    return {"activity": entries}


# ---------------- Static frontend ----------------

app.mount("/", StaticFiles(directory=str(ROOT / "app" / "static"), html=True), name="static")
