"""Folder-tree scanning for the archive root."""
import os
from pathlib import Path
from collections import defaultdict

IGNORED_DIRS = {".git", ".DS_Store", "__pycache__", ".pytest_cache", "node_modules"}
IGNORED_EXT = {".tmp", ".part", ".crdownload", ".lock"}


def _is_ignored(name: str) -> bool:
    return name in IGNORED_DIRS or name.startswith(".") and name not in (".gitkeep",)


def build_tree(root: str, max_depth: int = 6) -> dict:
    """
    Return a nested dict describing the archive structure.
    Each node: {name, path, type: 'dir'|'file', size, children (dirs only), file_count}
    Files are aggregated per folder (names + count) to keep the prompt compact.
    """
    rootp = Path(root).resolve()
    if not rootp.is_dir():
        return {"name": root, "path": root, "type": "dir", "exists": False,
                "children": [], "file_count": 0, "files": []}

    def walk(p: Path, depth: int) -> dict:
        node = {
            "name": p.name or str(p),
            "path": str(p),
            "type": "dir",
            "exists": True,
            "children": [],
            "files": [],
            "file_count": 0,
        }
        buckets = defaultdict(list)
        counts = defaultdict(int)
        try:
            entries = list(os.scandir(p))
        except OSError:
            return node
        dirs = []
        for e in entries:
            name = e.name
            if _is_ignored(name):
                continue
            if e.is_dir(follow_symlinks=False):
                dirs.append(e)
            else:
                ext = os.path.splitext(name)[1].lower()
                if ext in IGNORED_EXT:
                    continue
                counts[ext] += 1
                if len(buckets[ext]) < 5:
                    buckets[ext].append(name)
        node["file_count"] = sum(counts.values())
        node["files"] = [f for names in buckets.values() for f in names]
        node["extensions"] = {k: v for k, v in counts.items()}
        if depth < max_depth:
            for e in sorted(dirs, key=lambda d: d.name.lower()):
                node["children"].append(walk(Path(e.path), depth + 1))
        else:
            node["truncated"] = True
        return node

    return walk(rootp, 0)


def flatten_dirs(node: dict, out: list | None = None) -> list[str]:
    """All directory paths as a flat list (for AI prompt / validation)."""
    if out is None:
        out = []
    if node.get("type") == "dir" and node.get("exists", True):
        out.append(node["path"])
        for c in node.get("children", []):
            flatten_dirs(c, out)
    return out


def compact_summary(node: dict, indent: str = "", lines: list | None = None, max_lines: int = 220) -> list[str]:
    """ASCII tree summarising the archive for the AI prompt."""
    if lines is None:
        lines = []
    if len(lines) >= max_lines:
        lines.append("... (truncated)")
        return lines
    label = node["name"] or node["path"]
    meta = []
    if node.get("file_count"):
        meta.append(f"{node['file_count']} files")
    if node.get("extensions"):
        exts = ", ".join(f"{k or 'noext'}:{v}" for k, v in list(node["extensions"].items())[:6])
        meta.append(exts)
    lines.append(f"{indent}{label}/" + (f"  [{'; '.join(meta)}]" if meta else ""))
    for f in node.get("files", [])[:5]:
        if len(lines) >= max_lines:
            break
        lines.append(f"{indent}  {f}")
    for c in node.get("children", []):
        compact_summary(c, indent + "  ", lines, max_lines)
    return lines
