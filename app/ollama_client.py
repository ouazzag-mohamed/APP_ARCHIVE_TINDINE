"""Ollama client: vision analysis + tool-calling loop for gemma4:e2b (CPU friendly)."""
import base64
import json
import re
import requests

from . import config


class OllamaError(Exception):
    pass


def _client():
    url = config.get("ollama_url")
    if not url:
        raise OllamaError("Ollama URL is not configured")
    return url.rstrip("/")


def is_available() -> tuple[bool, str]:
    try:
        r = requests.get(f"{_client()}/api/tags", timeout=4)
        r.raise_for_status()
        names = [m["name"] for m in r.json().get("models", [])]
        model = config.get("model")
        if not any(n == model or n.split(":")[0] == model.split(":")[0] for n in names):
            return False, f"Ollama reachable, but model '{model}' not found. Run: ollama pull {model}"
        return True, "ok"
    except requests.RequestException as e:
        return False, f"Cannot reach Ollama at {_client()}: {e}"


def encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def chat(messages: list[dict], tools: list[dict] | None = None,
         timeout: int = 600, temperature: float = 0.2, num_predict: int = 900) -> dict:
    """Single chat turn. Returns raw Ollama response dict."""
    payload = {
        "model": config.get("model"),
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
            # CPU-friendly defaults; keep context tight for speed
            "num_ctx": 8192,
        },
    }
    if tools:
        payload["tools"] = tools
    try:
        r = requests.post(f"{_client()}/api/chat", json=payload, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        raise OllamaError(f"Ollama request failed: {e}") from e
    return r.json()


def extract_json(text: str) -> dict:
    """Best-effort JSON extraction from a model response."""
    if not text:
        raise OllamaError("Empty response from model")
    # fenced ```json blocks
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    else:
        # first balanced {...}
        start = text.find("{")
        if start == -1:
            raise OllamaError(f"No JSON object in model output:\n{text[:300]}")
        depth = 0
        end = start
        in_str = False
        esc = False
        for i, ch in enumerate(text[start:], start):
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"' and not esc:
                in_str = not in_str
            if not in_str:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
        text = text[start:end]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise OllamaError(f"Invalid JSON from model: {e}\n{text[:300]}") from e


SYSTEM_PROMPT = """You are the classification engine of a local smart document archiving app.
You receive: (1) a scanned document image (Arabic and/or English), (2) the current archive folder tree.

Your job:
1. Read the document and identify: document type, title, date, sender/issuer, key content, and language.
2. Choose the best existing destination folder from the archive tree for this document.
3. If NO existing folder fits, propose creating exactly ONE logical subfolder; set "create_folder": true
   and give a relative "target_dir" under the most suitable parent folder.
4. Generate a clean, standardized PDF file name: YYYY-MM-DD_Document_Title.pdf
   - Use the document's date if visible, otherwise use today's date given by the user.
   - Title: short, descriptive, Title_Case_English or clearly readable Arabic; no spaces (use _), no illegal characters.
   - Always end with .pdf
5. Write a one-sentence Arabic summary and a one-sentence English summary.

Respond with ONLY a JSON object, no other text, in exactly this schema:
{
  "language": "ar|en|mixed",
  "doc_type": "invoice|contract|id_card|receipt|letter|report|certificate|other",
  "title": "short document title",
  "issuer": "sender or organization or empty",
  "date": "YYYY-MM-DD or empty if unknown",
  "confidence": 0.0,
  "create_folder": false,
  "target_dir": "ABSOLUTE or root-relative destination directory path",
  "filename": "YYYY-MM-DD_Document_Title.pdf",
  "summary_ar": "...",
  "summary_en": "..."
}
Rules: target_dir MUST be an existing folder path from the tree unless create_folder is true.
filename MUST match ^\\d{4}-\\d{2}-\\d{2}_[A-Za-z0-9\\u0600-\\u06FF_\\-]+\\.pdf$
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "save_pdf_to_archive",
            "description": "Create a PDF from the scanned image and save it into the archive folder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_dir": {"type": "string", "description": "Destination directory inside the archive"},
                    "filename": {"type": "string", "description": "PDF file name, e.g. 2026-01-31_Invoice_Acme.pdf"},
                    "create_folder": {"type": "boolean", "description": "Whether target_dir must be created"},
                },
                "required": ["target_dir", "filename"],
            },
        },
    },
]


def analyze_document(image_path: str, tree_summary: str, today: str) -> dict:
    """Send the document image + archive tree to Gemma and return the structured plan."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Today's date: {today}\n\n"
                f"=== ARCHIVE FOLDER TREE ===\n{tree_summary}\n\n"
                "=== DOCUMENT IMAGE ATTACHED ===\n"
                "Analyze the image and return the JSON plan now."
            ),
            "images": [encode_image(image_path)],
        },
    ]
    resp = chat(messages, timeout=900, num_predict=1200)
    content = resp.get("message", {}).get("content", "")
    plan = extract_json(content)
    plan["_raw"] = content
    return plan


def confirm_with_tool(plan: dict, image_path: str, tree_summary: str, today: str) -> dict:
    """
    Second-stage tool-calling turn: give the model the save_pdf_to_archive tool and let it
    finalize the filing decision. Returns {'tool_called': bool, 'args': {...}}.
    On models without native tool support this gracefully returns tool_called=False.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Today's date: {today}\n\nARCHIVE TREE:\n{tree_summary}\n\n"
                "Decide the filing for the attached document. When ready, call "
                "save_pdf_to_archive with target_dir, filename and create_folder. "
                "Then reply with the final JSON plan only."
            ),
            "images": [encode_image(image_path)],
        },
    ]
    try:
        resp = chat(messages, tools=TOOLS, timeout=900, num_predict=1200)
    except OllamaError:
        return {"tool_called": False, "args": None}
    msg = resp.get("message", {})
    calls = msg.get("tool_calls") or []
    if calls:
        args = calls[0].get("function", {}).get("arguments") or {}
        return {"tool_called": True, "args": args}
    # Fall back to parsing JSON content if the model answered inline
    try:
        return {"tool_called": False, "args": extract_json(msg.get("content", ""))}
    except OllamaError:
        return {"tool_called": False, "args": None}
