"""Content-addressed store for imported fonts and logo images.

Assets are identified by a hash of their bytes, so projects reference them by
id instead of absolute paths.  Saved projects embed copies of every asset they
use (see ``project.save_project``).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

FONT_EXTS = {".ttf", ".otf"}
LOGO_EXTS = {".png"}
MAX_ASSET_BYTES = 30 * 1024 * 1024


class AssetError(ValueError):
    pass


def default_workspace():
    base = os.environ.get("TIDES_DICE_HOME")
    if base:
        return Path(base)
    return Path.home() / ".tides_dice_studio"


class AssetStore:
    def __init__(self, root=None):
        self.root = Path(root or default_workspace()) / "assets"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._meta_path = self.root / "index.json"
        try:
            self._meta = json.loads(self._meta_path.read_text("utf-8"))
        except (OSError, ValueError):
            self._meta = {}

    def put(self, data: bytes, name: str, kind: str) -> dict:
        if not data:
            raise AssetError("file is empty")
        if len(data) > MAX_ASSET_BYTES:
            raise AssetError("file is larger than 30 MB")
        ext = Path(name).suffix.lower()
        allowed = FONT_EXTS if kind == "font" else LOGO_EXTS if kind == "logo" else None
        if allowed is None:
            raise AssetError(f"unknown asset kind {kind!r}")
        if ext not in allowed:
            raise AssetError(f"{kind} files must be one of: {', '.join(sorted(allowed))}")
        aid = hashlib.sha256(data).hexdigest()[:24]
        with self._lock:
            path = self.root / f"{aid}{ext}"
            if not path.exists():
                path.write_bytes(data)
            self._meta[aid] = {"name": Path(name).name, "kind": kind, "ext": ext, "size": len(data)}
            self._meta_path.write_text(json.dumps(self._meta, indent=1), "utf-8")
        return {"id": aid, "name": Path(name).name, "kind": kind}

    def info(self, aid):
        return self._meta.get(aid)

    def path(self, aid):
        m = self._meta.get(aid)
        if not m:
            return None
        p = self.root / f"{aid}{m['ext']}"
        return p if p.exists() else None

    def get(self, aid):
        p = self.path(aid)
        return p.read_bytes() if p else None

    def has(self, aid):
        return self.path(aid) is not None
