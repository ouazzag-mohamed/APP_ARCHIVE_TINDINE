"""Capture sources: SANE scanner (Linux), WIA scanner (Windows), webcam (OpenCV)."""
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


def scanner_available() -> bool:
    if IS_WINDOWS:
        try:
            import comtypes  # noqa: F401
            return True
        except ImportError:
            return False
    return shutil.which("scanimage") is not None


def list_scanners() -> list[str]:
    """Return connected scanner device names/IDs."""
    if IS_WINDOWS:
        try:
            import comtypes.client
            dm = comtypes.client.CreateObject("WIA.DeviceManager")
            n = dm.DeviceInfos.Count
            return [dm.DeviceInfos(i).Properties("Name").Value for i in range(1, n + 1)]
        except Exception:
            return []
    if not shutil.which("scanimage"):
        return []
    try:
        out = subprocess.run(["scanimage", "-L"], capture_output=True, text=True, timeout=20)
        devices = []
        for line in out.stdout.splitlines():
            if "device" in line and "`" in line:
                # devices found: `name` is a ...
                parts = line.split("`")
                if len(parts) >= 2:
                    devices.append(parts[1].split("'")[0])
        return devices
    except Exception:
        return []


def _scan_windows(dpi: int = 300) -> str:
    """
    Windows: WIA (Windows Image Acquisition) via comtypes.
    Opens the scanner's native dialog (device choice, color mode, DPI...),
    then grabs the acquired image into a temp file.
    """
    import comtypes.client

    tmp_dir = Path(tempfile.gettempdir())
    before = {p.name for p in tmp_dir.glob("*.bmp")} | {p.name for p in tmp_dir.glob("*.png")}

    dialog = comtypes.client.CreateObject("WIA.CommonDialog")
    device = dialog.ShowSelectDevice()          # native chooser (auto-skips if 1 device)
    if device is None:
        raise RuntimeError("No scanner selected")
    images = dialog.ShowAcquisitionWizard(device)   # native scan dialog
    if images is None or images.Count == 0:
        raise RuntimeError("Scan cancelled or empty")

    # Save the first acquired image via WIA's own SaveFile; fall back to
    # detecting the wizard's temp file in %TEMP%.
    out = tmp_dir / f"scan_{int(time.time()*1000)}.png"
    try:
        images.Item(1).SaveFile(str(out))
        if out.exists() and out.stat().st_size > 0:
            return str(out)
    except Exception:
        pass

    # Fallback: the wizard wrote acquired images into %TEMP%; find the new one
    after = [p for p in list(tmp_dir.glob("*.bmp")) + list(tmp_dir.glob("*.png"))
             if p.name not in before]
    if not after:
        raise RuntimeError("Scanner did not return an image file")

    newest = max(after, key=lambda p: p.stat().st_mtime)
    out.write_bytes(newest.read_bytes())
    try:
        newest.unlink()
    except OSError:
        pass
    return str(out)


def scan_to_image(device: str | None = None, dpi: int = 300) -> str:
    """Capture a scan to a temp image; returns the file path."""
    if IS_WINDOWS:
        return _scan_windows(dpi)
    if not shutil.which("scanimage"):
        raise RuntimeError("scanimage (SANE) not installed. On Ubuntu: sudo apt install sane-utils")
    cmd = ["scanimage", "--format=png", f"--resolution={dpi}"]
    if device:
        cmd = ["scanimage", "-d", device, "--format=png", f"--resolution={dpi}"]
    out = subprocess.run(cmd, capture_output=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"Scan failed: {out.stderr.decode(errors='ignore')[:400]}")
    tmp = Path(tempfile.gettempdir()) / f"scan_{int(time.time()*1000)}.png"
    tmp.write_bytes(out.stdout)
    return str(tmp)


def webcam_available() -> bool:
    try:
        import cv2  # noqa
        return True
    except ImportError:
        return False


def webcam_snapshot(camera_index: int = 0) -> str:
    try:
        import cv2
    except ImportError:
        raise RuntimeError("opencv-python-headless is not installed (pip install opencv-python-headless)")
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open webcam {camera_index}")
    # Warm up a few frames for exposure
    for _ in range(8):
        cap.read()
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError("Webcam capture failed")
    tmp = Path(tempfile.gettempdir()) / f"cam_{int(time.time()*1000)}.png"
    cv2.imwrite(str(tmp), frame)
    return str(tmp)
