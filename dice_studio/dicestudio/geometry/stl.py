"""Binary STL writer/reader."""
from __future__ import annotations

import struct

import numpy as np

UNITS = {"mm": 1.0, "cm": 0.1, "in": 1.0 / 25.4}


def stl_bytes(vertices, tris, name="dice", unit="mm"):
    if unit not in UNITS:
        raise ValueError(f"unit must be one of {list(UNITS)}")
    V = np.asarray(vertices, dtype=np.float64) * UNITS[unit]
    T = np.asarray(tris, dtype=np.int64)
    p = V[T].astype(np.float32)
    n = np.cross(p[:, 1].astype(np.float64) - p[:, 0], p[:, 2].astype(np.float64) - p[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.divide(n, ln, out=np.zeros_like(n), where=ln > 0).astype(np.float32)
    rec = np.zeros(len(T), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
    rec["n"] = n
    rec["v"] = p
    header = f"Tides Dice Studio | {name} | units={unit}".encode("ascii", "replace")[:80].ljust(80, b" ")
    return header + struct.pack("<I", len(T)) + rec.tobytes()


def write_stl(path, vertices, tris, name="dice", unit="mm"):
    data = stl_bytes(vertices, tris, name, unit)
    with open(path, "wb") as fh:
        fh.write(data)
    return len(data)


def read_stl(path_or_bytes):
    data = path_or_bytes
    if not isinstance(data, (bytes, bytearray)):
        with open(path_or_bytes, "rb") as fh:
            data = fh.read()
    n = struct.unpack("<I", data[80:84])[0]
    if len(data) != 84 + 50 * n:
        raise ValueError("not a binary STL (size mismatch)")
    rec = np.frombuffer(data[84:], dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")], count=n)
    pts = rec["v"].reshape(-1, 3).astype(np.float64)
    uniq, inv = np.unique(pts, axis=0, return_inverse=True)
    return uniq, inv.reshape(-1, 3), rec["n"].astype(np.float64)
