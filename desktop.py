"""
Smart Archive — Desktop mode (native window with native OS dialogs).

Runs the same FastAPI server, but inside a native desktop window (pywebview).
This enables the real system folder-picker dialog (GTK/Qt) with absolute paths,
which plain browsers cannot provide.

Usage:  python desktop.py        (installs pywebview automatically if missing)
"""
import os
os.environ.setdefault("QT_API", "pyqt6")  # force qtpy onto PyQt6 (has WebEngine)
import socket
import threading
import time
import uvicorn

HOST: str = "127.0.0.1"
PORT: int = 8765


class NativeAPI:
    """JS bridge: window.pywebview.api.*"""

    def select_folder(self, start: str | None = None):
        """Open the native system folder chooser; return the absolute path or None."""
        import webview
        windows = webview.windows
        dialog_kind = getattr(webview.FileDialog, "FOLDER", webview.FOLDER_DIALOG)
        result = windows[0].create_file_dialog(
            dialog_kind, directory=start or "", allow_multiple=False)
        if result:
            return result[0]
        return None


def wait_server(url: str, timeout: float = 15.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection((HOST, PORT), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def main():
    import webview

    config = uvicorn.Config("app.main:app", host=HOST, port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()

    if not wait_server(f"http://{HOST}:{PORT}"):
        raise RuntimeError("Server failed to start")

    window = webview.create_window(
        "🗂️ Smart Archive — AI Document Filing",
        f"http://{HOST}:{PORT}",
        width=1400,
        height=900,
        min_size=(1000, 640),
        js_api=NativeAPI(),   # expose window.pywebview.api.select_folder to the UI
    )
    # Prefer the Qt backend (PyQt6-WebEngine) — robust on Linux without system WebKit typelibs
    try:
        webview.start(gui="qt")
    except Exception as e:
        print(f"Qt backend unavailable ({e}); trying default backend…")
        webview.start()


if __name__ == "__main__":
    main()
