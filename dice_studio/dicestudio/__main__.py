"""Launch the studio:  python -m dicestudio [--port 8765] [--no-browser] [--workspace DIR]"""
import argparse
import logging

from .assets import default_workspace
from .server import serve


def main():
    ap = argparse.ArgumentParser(prog="dicestudio", description="Tides Dice Studio - parametric resin dice designer")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--workspace", default=None, help=f"data folder (default {default_workspace()})")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    ws = a.workspace or default_workspace()
    ws_path = __import__("pathlib").Path(ws)
    ws_path.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if a.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(ws_path / "dicestudio.log", encoding="utf-8")],
    )
    serve(a.port, not a.no_browser, ws)


if __name__ == "__main__":
    main()
