#!/usr/bin/env bash
# Launch Smart Archive (FastAPI + local Ollama gemma4:e2b)
set -e
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
fi
exec ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
