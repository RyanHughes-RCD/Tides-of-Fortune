"""Engine service: cached die builds, validation reports and STL export.

Used by the HTTP server and the tests.  Builds are cached by spec hash, so
editing one die only rebuilds that die.
"""
from __future__ import annotations

import io
import json
import logging
import threading
import time
import zipfile
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .assets import AssetStore
from .geometry.builder import build_die
from .geometry.polyhedra import DIE_TYPES
from .geometry.stl import stl_bytes
from .geometry.validate import validate_mesh
from .project import resolve_die_spec, validate_project

log = logging.getLogger(__name__)


class ExportError(RuntimeError):
    pass


class Engine:
    def __init__(self, store: AssetStore, cache_size=96, workers=4):
        self.store = store
        self._cache = OrderedDict()
        self._inflight = {}
        self._lock = threading.Lock()
        self._cache_size = cache_size
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="build")

    # -- building ---------------------------------------------------------
    def build(self, spec):
        h = spec["hash"]
        with self._lock:
            if h in self._cache:
                self._cache.move_to_end(h)
                return self._cache[h]
            ev = self._inflight.get(h)
            owner = ev is None
            if owner:
                ev = self._inflight[h] = threading.Event()
        if not owner:
            ev.wait()
            with self._lock:
                if h in self._cache:
                    return self._cache[h]
            return self.build(spec)
        try:
            t0 = time.time()
            res = build_die(spec, self.store.get)
            log.info("built %s (%s) in %.2fs%s", spec["die"], h, time.time() - t0,
                     f" ERRORS: {res.errors}" if res.errors else "")
            with self._lock:
                self._cache[h] = res
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
            return res
        finally:
            with self._lock:
                self._inflight.pop(h, None)
            ev.set()

    def get_cached(self, h):
        with self._lock:
            return self._cache.get(h)

    def build_project(self, project, dice=None):
        p = validate_project(project)
        dice = dice or DIE_TYPES
        specs = {d: resolve_die_spec(p, d) for d in dice}
        futs = {d: self.pool.submit(self.build, s) for d, s in specs.items()}
        return p, {d: f.result() for d, f in futs.items()}

    # -- export -----------------------------------------------------------
    @staticmethod
    def file_name(prefix, die, blank):
        return f"{prefix}_{die.upper()}{'_Blank' if blank else ''}.stl"

    def export_items(self, project, which="all", die=None):
        """Yield (filename, kind, die, vertices, tris, report) for the requested meshes."""
        p, results = self.build_project(project, [die] if die else None)
        prefix = p["export"]["prefix"]
        items = []
        for d, r in results.items():
            if r.errors:
                raise ExportError(f"{d.upper()} could not be built: {'; '.join(r.errors)}")
            if which in ("all", "dice"):
                items.append((self.file_name(prefix, d, False), "die", d, r.outer_vertices, r.outer_tris,
                              r.outer_report))
            if which in ("all", "blanks"):
                items.append((self.file_name(prefix, d, True), "blank", d, r.blank_vertices, r.blank_tris,
                              r.blank_report))
        return p, results, items

    def validation_report(self, project, which="all", die=None):
        p, results, items = self.export_items(project, which, die)
        meshes = [dict(file=f, kind=k, die=d, **rep) for f, k, d, _, _, rep in items]
        blanks = {d: r.blank_check for d, r in results.items()}
        warnings = {d: r.warnings for d, r in results.items() if r.warnings}
        ok = all(m["ok"] for m in meshes) and all(b and b["ok"] for b in blanks.values())
        return {"ok": ok, "meshes": meshes, "blank_checks": blanks, "warnings": warnings,
                "unit": p["export"]["unit"], "created": time.strftime("%Y-%m-%d %H:%M:%S")}

    def _check_export(self, p, items, results):
        bad = [f"{f}: {', '.join(rep['issues'])}" for f, _, _, _, _, rep in items if not rep["ok"]]
        for d, r in results.items():
            if r.blank_check and not r.blank_check["ok"] and any(k == "blank" and dd == d for _, k, dd, *_ in items):
                bad.append(f"{d.upper()} blank fit: {', '.join(r.blank_check['issues'])}")
        if bad and not p["export"]["allow_invalid"]:
            raise ExportError("validation failed, nothing was exported:\n" + "\n".join(bad))
        return bad

    def export_to_directory(self, project, directory, which="all", die=None):
        directory = Path(directory).expanduser()
        if not str(directory).strip():
            raise ExportError("choose an export directory")
        p, results, items = self.export_items(project, which, die)
        bad = self._check_export(p, items, results)
        directory.mkdir(parents=True, exist_ok=True)
        written = []
        for fname, kind, d, V, T, rep in items:
            data = stl_bytes(V, T, fname[:-4], p["export"]["unit"])
            (directory / fname).write_bytes(data)
            written.append({"file": str(directory / fname), "bytes": len(data), "ok": rep["ok"]})
        report = self.validation_report(project, which, die)
        report["written"] = written
        report["exported_with_issues"] = bad
        rp = directory / f"{p['export']['prefix']}_validation_report.json"
        rp.write_text(json.dumps(report, indent=2, default=float), "utf-8")
        return report

    def export_zip(self, project, which="all", die=None):
        p, results, items = self.export_items(project, which, die)
        self._check_export(p, items, results)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for fname, kind, d, V, T, rep in items:
                z.writestr(fname, stl_bytes(V, T, fname[:-4], p["export"]["unit"]))
            z.writestr(f"{p['export']['prefix']}_validation_report.json",
                       json.dumps(self.validation_report(project, which, die), indent=2, default=float))
        return buf.getvalue()


def revalidate_stl(data):
    """Re-read written STL bytes and validate them (used by tests and the export check)."""
    from .geometry.stl import read_stl

    V, T, _ = read_stl(data)
    return validate_mesh(V, T, "stl", expect_genus=0)
