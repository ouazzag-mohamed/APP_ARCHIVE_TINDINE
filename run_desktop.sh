#!/usr/bin/env bash
# Smart Archive — DESKTOP mode: native window + native system folder chooser
set -e
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
fi
# Linux: pywebview needs GTK backend
if ! python3 -c "import gi" 2>/dev/null; then
  echo "NOTE: if the window fails to open, install GTK bindings:"
  echo "  sudo apt install python3-gi gir1.2-webkit2-4.1"
fi
exec ./.venv/bin/python desktop.py
