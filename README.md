# 🗂️ Smart Archive — Local AI Document Archiving

A modern, fully-local desktop/web app that reads scanned documents (Arabic + English) with
**Gemma (`gemma4:e2b`) via Ollama**, decides the best destination folder inside your existing
archive structure, generates a standardized PDF filename (`YYYY-MM-DD_Document_Title.pdf`),
converts the scan to PDF, and files it — automatically or after your one-click confirmation.

Everything runs **100% locally on CPU** — no GPU, no cloud, no data leaves your machine.

---

## ✨ Features

| Feature | Detail |
|---|---|
| Archive folder integration | Configure any local root folder; full tree scan with file counts; live sidebar tree; click a folder to pre-fill the target |
| Upload & capture | Drag & drop (JPG/PNG/WEBP/BMP/TIFF), file browser, scanner (**WIA on Windows, SANE on Linux**), **webcam snapshot** (OpenCV) |
| AI vision | Image + folder tree sent to `gemma4:e2b` on Ollama; Arabic & English reading; structured JSON plan |
| Tool calling | `save_pdf_to_archive` function exposed to the model (`/api/tool-call`) plus a deterministic execution pipeline |
| Auto / Review mode | Toggle switch: Auto files instantly; Review pre-fills folder + filename for one-click edit/confirm |
| PDF creation | EXIF-rotated, high-quality JPEG-inside-PDF via `img2pdf`; auto date-prefix & filename sanitization; collision-safe naming |
| Safety | All writes constrained inside the archive root (path-escape protection) |
| UX | Dark/light mode, CPU-friendly spinners, success banner with **exact saved path**, Recent Archives log with quick-open links |
| Persistence | `config.json` settings + `activity_log.json` history |

## 📁 Project structure

```
APP_ARCHIVE_TINDINE/
├── run.sh / run.bat            # one-command launcher (creates venv)
├── requirements.txt
├── config.json                 # created on first run (archive root, model, mode…)
├── activity_log.json           # recent-archives history
├── uploads/                    # temporary staging of scanned images
├── Archive/                    # default archive root (changeable in Settings)
└── app/
    ├── main.py                 # FastAPI server & REST API
    ├── config.py               # persisted settings
    ├── tree_scanner.py         # folder-tree scan + AI prompt summary
    ├── ollama_client.py        # gemma4:e2b vision + tool-calling client
    ├── archiver.py             # PDF creation, safe filing, activity log
    ├── capture.py              # scanner (SANE) & webcam (OpenCV) sources
    └── static/                 # zero-build frontend (HTML/CSS/JS)
        ├── index.html
        ├── style.css
        └── app.js
```

## 🚀 Installation

### 1. Ollama + model

```bash
# Linux
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma4:e2b     # ≈5 GB download, runs fine on CPU

# Windows / macOS: install from https://ollama.com/download then same pull command
```

The model name is configurable in the app's Settings (e.g. swap to `gemma4:e2b:latest`
or another vision-capable Gemma variant).

### 2. App

```bash
cd APP_ARCHIVE_TINDINE
chmod +x run.sh && ./run.sh          # Linux / macOS
# or on Windows: run.bat
```

This creates a virtualenv, installs dependencies, and serves the UI at:

**http://127.0.0.1:8765**

Manual install instead:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

### 3. Optional extras

```bash
# Webcam snapshots
pip install opencv-python-headless

# Scanner support (Linux — SANE)
sudo apt install sane-utils
scanimage -L          # verify your scanner is detected
```

**Scanner support on Windows 11:** works automatically via **WIA (Windows Image Acquisition)** —
`comtypes` is installed by `requirements.txt`. The 🖨 Scanner button opens your scanner's own
native dialog (device, color mode, DPI), and the scanned image lands directly in the app.

## 🖥️ Usage

1. **Settings ⚙** → set your Archive folder (e.g. `/home/you/Documents/Archive`). The full
   existing tree is scanned and shown in the sidebar.
2. **Add a document** → drag & drop a scan, browse, or use 🖨 Scanner / 📷 Webcam.
3. Gemma reads the document (AR/EN) and returns: title, type, date, language, target folder,
   standardized PDF filename, and AR/EN summaries.
   - **Review Mode** (default): fields are pre-filled — edit anything, pick a tree folder,
     then click **💾 Save PDF to Archive**.
   - **Auto-Archive Mode** (toggle in the AI panel): the PDF is created and filed immediately.
4. The success banner and Recent Archives log show the **exact saved path**, with an
   **Open ↗** link to the PDF.
5. If no folder fits, tick **"Create this folder if missing"** — the AI proposes a logical
   subfolder and it is created on save.

## 🔌 API (for scripting / integrations)

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/settings` | GET/PUT | View/update config (archive root, model, mode…) |
| `/api/tree` | GET | Full archive tree |
| `/api/folders/create` | POST | Create a subfolder |
| `/api/upload` | POST (multipart) | Upload a document image |
| `/api/capture/scan` · `/api/capture/webcam` | POST | Acquire from scanner / webcam |
| `/api/analyze` | POST | Gemma vision → filing plan (JSON) |
| `/api/tool-call` | POST | Gemma native `save_pdf_to_archive` tool-call confirmation |
| `/api/archive` | POST | Execute: image → PDF → filed into archive (+ activity log) |
| `/api/activity` | GET/DELETE | Recent-archives log |

## ⚡ CPU performance tips

- `gemma4:e2b` on CPU typically takes **30–120 s** per document — the UI shows a
  purpose-built spinner ("CPU inference — this can take 30–120 s").
- Keep `num_ctx` modest (8192 in `ollama_client.py`) — already tuned.
- Prefer JPG scans at ~200–300 DPI; huge TIFFs are downscaled by the JPEG conversion.
- Close other heavy apps while archiving; Ollama uses all cores by default.
