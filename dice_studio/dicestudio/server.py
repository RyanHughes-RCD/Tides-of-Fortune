"""Local HTTP server for the dice studio UI (Python standard library only).

Binds to 127.0.0.1 only.  All geometry work happens here; the browser only
displays meshes it downloads from this server.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import struct
import subprocess
import sys
import threading
import traceback
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

from . import project as proj
from .assets import AssetError, AssetStore, default_workspace
from .engine import Engine, ExportError
from .geometry import design as deco
from .geometry import logo as logomod
from .geometry.polyhedra import DEFAULT_SIZES_MM, DIE_TYPES, SIZE_MEANING
from .geometry.text import (BuiltinFont, DIGITS, FontError, check_font_digits, geometry_to_svg_path, load_font,
                            text_shape)

log = logging.getLogger("dicestudio.server")
WEB = Path(__file__).parent / "web"
BUNDLED_FONTS = Path(__file__).parent / "fonts"


class ApiError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


class App:
    def __init__(self, workspace=None):
        self.workspace = Path(workspace or default_workspace())
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.projects_dir = self.workspace / "projects"
        self.projects_dir.mkdir(exist_ok=True)
        self.store = AssetStore(self.workspace)
        self.engine = Engine(self.store)

    # ---- API handlers (each takes a JSON body and returns JSON) ----------
    def api_config(self, body):
        return {
            "dice": DIE_TYPES,
            "default_sizes": DEFAULT_SIZES_MM,
            "size_meaning": SIZE_MEANING,
            "styles": deco.STYLES,
            "design_schema": deco.DESIGN_SCHEMA,
            "die_keys": deco.DIE_KEYS,
            "projects_dir": str(self.projects_dir),
            "export_dir": str(self.workspace / "exports"),
            "bundled_fonts": sorted(p.name for p in BUNDLED_FONTS.glob("*.ttf")),
        }

    def api_new(self, body):
        return {"project": proj.default_project(body.get("seed"), body.get("style", "classic"),
                                                float(body.get("density", 0.5)), body.get("name") or "MySet")}

    def api_validate_project(self, body):
        return {"project": proj.validate_project(body["project"])}

    def api_randomize(self, body):
        p = proj.validate_project(body["project"])
        scope = body.get("scope", "set")
        if scope == "set":
            p = proj.randomize_set(p, body.get("seed"))
        elif scope == "die":
            p = proj.regenerate_die(p, body["die"])
        elif scope == "design":
            p = proj.regenerate_design(p)
        elif scope == "reset_die":
            p = proj.reset_die(p, body["die"])
        elif scope == "reset_set":
            p = proj.reset_set(p)
        else:
            raise ApiError(f"unknown scope {scope}")
        return {"project": proj.validate_project(p)}

    def api_generate(self, body):
        p = proj.validate_project(body["project"])
        dice = body.get("dice") or DIE_TYPES
        _, results = self.engine.build_project(p, dice)
        return {"dice": {d: r.summary() for d, r in results.items()}}

    def api_validate(self, body):
        try:
            return {"report": self.engine.validation_report(body["project"], body.get("which", "all"),
                                                            body.get("die"))}
        except ExportError as exc:
            raise ApiError(str(exc))

    def api_export(self, body):
        p = proj.validate_project(body["project"])
        directory = body.get("directory") or p["export"]["directory"] or str(self.workspace / "exports")
        try:
            rep = self.engine.export_to_directory(p, directory, body.get("which", "all"), body.get("die"))
        except ExportError as exc:
            raise ApiError(str(exc))
        return {"report": rep, "directory": directory}

    def api_save(self, body):
        p = body["project"]
        path = body.get("path") or str(self.projects_dir / (proj.safe_filename(p.get("name", "MySet")) + proj.PROJECT_EXT))
        try:
            saved = proj.save_project(p, path, self.store)
        except proj.ProjectError as exc:
            raise ApiError(str(exc))
        return {"path": saved}

    def api_open(self, body):
        path = body.get("path")
        if not path:
            raise ApiError("no project path given")
        if not Path(path).exists():
            raise ApiError(f"file not found: {path}")
        return {"project": proj.open_project(path, self.store), "path": path}

    def api_list_projects(self, body):
        files = sorted(self.projects_dir.glob("*" + proj.PROJECT_EXT), key=lambda p: -p.stat().st_mtime)
        return {"projects": [{"path": str(f), "name": f.stem} for f in files[:50]]}

    def api_duplicate(self, body):
        return {"project": proj.duplicate_project(proj.validate_project(body["project"]), body.get("name"))}

    def api_font_preview(self, body):
        aid = body.get("asset_id")
        weight = body.get("weight", 600)
        try:
            if aid:
                data = self.store.get(aid)
                if data is None:
                    raise ApiError("font asset not found; import it again")
                font = load_font(data, (self.store.info(aid) or {}).get("name", "font"), weight, aid)
            else:
                font = BuiltinFont(weight)
            missing = check_font_digits(font)
            fb = BuiltinFont(600)
            shapes = []
            x = 0.0
            for s in ["0123456789", "6", "9", "00", "20"]:
                ts = text_shape(font, s, 10.0, float(body.get("embolden_mm", 0)) * 4, fallback=fb,
                                marker="underline" if s in ("6", "9") else None)
                b = ts.geom.bounds
                shapes.append({"text": s, "path": geometry_to_svg_path(ts.geom),
                               "bbox": [b[0], -b[3], b[2] - b[0], b[3] - b[1]]})
        except FontError as exc:
            raise ApiError(str(exc))
        return {"name": font.name, "missing": missing, "shapes": shapes,
                "variable_weight": getattr(font, "supports_weight", True),
                "axes": getattr(font, "axes", {})}

    def api_logo_preview(self, body):
        lg = body.get("logo") or {}
        aid = (lg.get("asset") or {}).get("id")
        data = self.store.get(aid) if aid else None
        if data is None:
            raise ApiError("no logo image imported")
        try:
            shape = logomod.logo_shape(data, int(lg.get("threshold", 128)), bool(lg.get("invert")),
                                       lg.get("mask_mode", "auto"), float(lg.get("simplify_px", 0.6)))
            png = logomod.mask_preview_png(data, int(lg.get("threshold", 128)), bool(lg.get("invert")),
                                           lg.get("mask_mode", "auto"))
        except logomod.LogoError as exc:
            raise ApiError(str(exc))
        width = float(lg.get("width_mm", 6.0))
        placed = logomod.place_logo(shape, width)
        if lg.get("remove_fine"):
            placed = logomod.remove_fine_details(placed, float(lg.get("min_feature_mm", 0.3)))
        rep = logomod.fine_detail_report(placed, float(lg.get("min_feature_mm", 0.3)),
                                         float(lg.get("min_feature_mm", 0.3)))
        b = placed.bounds if not placed.is_empty else (0, 0, 1, 1)
        return {"mask_png": png, "outline": geometry_to_svg_path(placed),
                "bbox": [b[0], -b[3], b[2] - b[0], b[3] - b[1]], "width_mm": width,
                "height_mm": width * shape.aspect, "components": shape.components, "holes": shape.holes,
                "mask_mode": shape.mask_mode, "coverage": shape.coverage, "warnings": rep["warnings"],
                "thin_fraction": rep["thin_fraction"]}

    def api_dialog(self, body):
        """Native file dialog on this machine (local app).  Runs Tk in a subprocess."""
        kind = body.get("kind")
        initial = body.get("initial") or str(self.workspace)
        script = {
            "directory": "p=fd.askdirectory(initialdir=I,title='Choose export folder')",
            "save_project": "p=fd.asksaveasfilename(initialdir=I,defaultextension='.tdice',"
                            "filetypes=[('Dice project','*.tdice')],title='Save project')",
            "open_project": "p=fd.askopenfilename(initialdir=I,filetypes=[('Dice project','*.tdice')],"
                            "title='Open project')",
            "font": "p=fd.askopenfilename(initialdir=I,filetypes=[('Fonts','*.ttf *.otf')],title='Import font')",
            "logo": "p=fd.askopenfilename(initialdir=I,filetypes=[('PNG image','*.png')],title='Import logo')",
        }.get(kind)
        if script is None:
            raise ApiError("unknown dialog")
        code = ("import tkinter as tk, tkinter.filedialog as fd, sys\nI=sys.argv[1]\nr=tk.Tk();r.withdraw();"
                "r.attributes('-topmost',True)\n" + script + "\nprint(p or '')")
        try:
            out = subprocess.run([sys.executable, "-c", code, initial], capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ApiError(f"native dialog unavailable: {exc}")
        if out.returncode != 0:
            raise ApiError("native dialog unavailable on this system; type the path instead")
        return {"path": out.stdout.strip()}

    def api_import_path(self, body):
        """Import a font/logo from a local path (used with the native dialog)."""
        path = Path(body.get("path", ""))
        if not path.is_file():
            raise ApiError(f"file not found: {path}")
        return self._import(path.read_bytes(), path.name, body.get("kind"))

    def api_bundled_font(self, body):
        name = Path(body.get("name", "")).name
        path = BUNDLED_FONTS / name
        if not path.is_file():
            raise ApiError("bundled font not found")
        return self._import(path.read_bytes(), name, "font")

    def _import(self, data, name, kind):
        try:
            ref = self.store.put(data, name, kind)
        except AssetError as exc:
            raise ApiError(str(exc))
        info = {}
        try:
            if kind == "font":
                f = load_font(data, name)
                missing = check_font_digits(f)
                if len(missing) == len(DIGITS):
                    raise ApiError("this font contains no digits 0-9 and cannot be used for numerals")
                info = {"missing": missing, "axes": f.axes, "variable_weight": f.supports_weight}
            else:
                im = logomod.load_png(data)
                info = {"width_px": im.width_px, "height_px": im.height_px, "has_alpha": im.has_alpha}
        except (FontError, logomod.LogoError) as exc:
            raise ApiError(str(exc))
        return {"asset": {"id": ref["id"], "name": ref["name"]}, "info": info}


def mesh_payload(V, T):
    V = np.ascontiguousarray(V, dtype="<f4")
    T = np.ascontiguousarray(T, dtype="<u4")
    return struct.pack("<II", len(V), len(T)) + V.tobytes() + T.tobytes()


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TidesDiceStudio/1.0"

        def log_message(self, fmt, *args):
            log.debug("%s - %s", self.address_string(), fmt % args)

        def _send(self, status, body: bytes, ctype):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status=200):
            self._send(status, json.dumps(obj, default=_jsonable).encode(), "application/json")

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(url.query)
            try:
                if url.path.startswith("/api/mesh/"):
                    h = url.path.rsplit("/", 1)[1]
                    r = app.engine.get_cached(h)
                    if r is None or r.errors:
                        return self._json({"error": "mesh not available; regenerate"}, 404)
                    part = q.get("part", ["outer"])[0]
                    V, T = (r.blank_vertices, r.blank_tris) if part == "blank" else (r.outer_vertices, r.outer_tris)
                    return self._send(200, mesh_payload(V, T), "application/octet-stream")
                path = url.path
                if path == "/":
                    path = "/index.html"
                f = (WEB / path.lstrip("/")).resolve()
                if WEB.resolve() not in f.parents or not f.is_file():
                    return self._send(404, b"not found", "text/plain")
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                if f.suffix == ".js":
                    ctype = "text/javascript"
                return self._send(200, f.read_bytes(), ctype)
            except Exception as exc:  # pragma: no cover
                log.exception("GET failed")
                return self._json({"error": str(exc)}, 500)

        def do_POST(self):
            url = urllib.parse.urlparse(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            try:
                if url.path == "/api/upload":
                    q = urllib.parse.parse_qs(url.query)
                    name = q.get("name", ["file"])[0]
                    kind = q.get("kind", [""])[0]
                    return self._json(app._import(raw, name, kind))
                if url.path == "/api/open_upload":
                    return self._json({"project": proj.open_project(raw, app.store)})
                if url.path == "/api/download_project":
                    import tempfile
                    body = json.loads(raw or b"{}")
                    with tempfile.TemporaryDirectory() as td:
                        p = proj.save_project(body["project"], Path(td) / "p.tdice", app.store)
                        return self._send(200, Path(p).read_bytes(), "application/zip")
                if url.path == "/api/export_zip":
                    body = json.loads(raw or b"{}")
                    try:
                        data = app.engine.export_zip(body["project"], body.get("which", "all"), body.get("die"))
                    except ExportError as exc:
                        raise ApiError(str(exc))
                    return self._send(200, data, "application/zip")
                name = url.path.removeprefix("/api/")
                fn = getattr(app, "api_" + name, None)
                if fn is None:
                    return self._json({"error": f"unknown endpoint {url.path}"}, 404)
                body = json.loads(raw or b"{}")
                return self._json(fn(body))
            except (ApiError, proj.ProjectError) as exc:
                return self._json({"error": str(exc)}, getattr(exc, "status", 400))
            except (KeyError, ValueError, TypeError) as exc:
                log.warning("bad request %s: %s", url.path, exc)
                return self._json({"error": f"invalid request: {exc}"}, 400)
            except Exception as exc:
                log.error("POST %s failed:\n%s", url.path, traceback.format_exc())
                return self._json({"error": f"internal error: {exc}"}, 500)

    return Handler


def _jsonable(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


def serve(port=8765, open_browser=True, workspace=None):
    app = App(workspace)
    httpd = None
    for p in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), make_handler(app))
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit("no free port found")
    url = f"http://127.0.0.1:{port}/"
    log.info("Tides Dice Studio running at %s (workspace %s)", url, app.workspace)
    print(f"\n  Tides Dice Studio is running at {url}\n  Close this window or press Ctrl+C to quit.\n", flush=True)
    if open_browser:
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
