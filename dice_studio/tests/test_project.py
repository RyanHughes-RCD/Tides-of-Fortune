import copy
import json
import threading
import urllib.request

import pytest

from conftest import make_font, make_logo_png
from dicestudio import project as proj
from dicestudio.geometry.polyhedra import DIE_TYPES


def test_seed_reproducibility(engine):
    a = proj.default_project(seed=777, style="crystal", density=0.8)
    b = proj.default_project(seed=777, style="crystal", density=0.8)
    assert a["design"] == b["design"]
    ha = {d: proj.resolve_die_spec(a, d)["hash"] for d in DIE_TYPES}
    hb = {d: proj.resolve_die_spec(b, d)["hash"] for d in DIE_TYPES}
    assert ha == hb
    ra = engine.build(proj.resolve_die_spec(a, "d12"))
    from dicestudio.geometry.builder import build_die
    rb = build_die(proj.resolve_die_spec(b, "d12"), engine.store.get)  # fresh, uncached build
    assert (ra.outer_vertices == rb.outer_vertices).all() and (ra.outer_tris == rb.outer_tris).all()
    c = proj.default_project(seed=778, style="crystal", density=0.8)
    assert c["design"] != a["design"]


def test_randomize_respects_locks():
    p = proj.default_project(seed=1, style="geometric")
    p["locks"] = ["d20_shape", "d8_height"]
    p["design"]["d20_shape"] = "bipyramid"
    p["design"]["d8_height"] = 1.33
    changed = False
    for s in range(2, 12):
        q = proj.randomize_set(p, seed=s)
        assert q["design"]["d20_shape"] == "bipyramid"
        assert q["design"]["d8_height"] == 1.33
        changed |= q["design"] != p["design"]
    assert changed


def test_regenerate_single_die_only_changes_that_die():
    p = proj.default_project(seed=5, style="mixed", density=0.9)
    before = {d: proj.resolve_die_spec(p, d)["hash"] for d in DIE_TYPES}
    for _ in range(3):
        p = proj.regenerate_die(p, "d12")
    after = {d: proj.resolve_die_spec(p, d)["hash"] for d in DIE_TYPES}
    assert before["d12"] != after["d12"]
    assert all(before[d] == after[d] for d in DIE_TYPES if d != "d12")
    p = proj.reset_die(p, "d12")
    assert proj.resolve_die_spec(p, "d12")["hash"] == before["d12"]


def test_validation_messages():
    p = proj.default_project(seed=1)
    bad = copy.deepcopy(p)
    bad["numbers"]["depth_mm"] = 9
    with pytest.raises(proj.ProjectError, match="Engraving depth"):
        proj.validate_project(bad)
    bad = copy.deepcopy(p)
    bad["design"]["d12_shape"] = "sphere"
    with pytest.raises(proj.ProjectError, match="D12 Shape"):
        proj.validate_project(bad)
    bad = copy.deepcopy(p)
    bad["numbers"]["d10_top_order"] = [1, 8, 3, 9, 5]
    with pytest.raises(proj.ProjectError, match="opposite"):
        proj.validate_project(bad)


def test_save_and_reopen_with_assets(engine, store, tmp_path):
    font = store.put(make_font("otf"), "MyFont.otf", "font")
    logo = store.put(make_logo_png(), "MyLogo.png", "logo")
    p = proj.default_project(seed=99, style="geometric", name="Geo Set")
    p["font"]["asset"] = {"id": font["id"], "name": font["name"]}
    p["logo"].update({"asset": {"id": logo["id"], "name": logo["name"]}, "enabled": True, "threshold": 90})
    p["blank"]["clearance_mm"] = 0.6
    p["numbers"]["depth_mm"] = 0.9
    p["dice"]["d6"]["offset_mm"] = [0.3, -0.2]
    p["export"]["unit"] = "mm"
    p = proj.validate_project(p)
    path = proj.save_project(p, tmp_path / "gothic", store)
    assert path.endswith(".tdice")

    # reopen into a completely fresh asset store (e.g. another computer)
    from dicestudio.assets import AssetStore
    other = AssetStore(tmp_path / "other_ws")
    q = proj.open_project(path, other)
    assert q == p
    assert other.get(font["id"]) == store.get(font["id"])
    assert other.get(logo["id"]) == store.get(logo["id"])
    hp = {d: proj.resolve_die_spec(p, d)["hash"] for d in DIE_TYPES}
    hq = {d: proj.resolve_die_spec(q, d)["hash"] for d in DIE_TYPES}
    assert hp == hq
    from dicestudio.geometry.builder import build_die
    r = build_die(proj.resolve_die_spec(q, "d20"), other.get)
    assert r.ok and r.info["logo"]["components"] == 2

    dup = proj.duplicate_project(q, "Experiment")
    assert dup["name"] == "Experiment" and dup["design"] == q["design"]


def test_open_rejects_garbage(store, tmp_path):
    f = tmp_path / "x.tdice"
    f.write_bytes(b"nope")
    with pytest.raises(proj.ProjectError):
        proj.open_project(str(f), store)


def test_http_api_end_to_end(tmp_path):
    from http.server import ThreadingHTTPServer

    from dicestudio.server import App, make_handler

    app = App(tmp_path / "ws")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def post(path, body, raw=False):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        req = urllib.request.Request(base + path, data=data, method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                out = r.read()
                return out if raw else json.loads(out)
        except urllib.error.HTTPError as e:
            return json.loads(e.read())

    try:
        p = post("/api/new", {"seed": 3, "style": "geometric"})["project"]
        gen = post("/api/generate", {"project": p, "dice": ["d6", "d20"]})
        assert gen["dice"]["d6"]["ok"]
        h = gen["dice"]["d20"]["hash"]
        with urllib.request.urlopen(f"{base}/api/mesh/{h}?part=blank") as r:
            assert len(r.read()) > 100
        up = post("/api/upload?kind=font&name=t.ttf", make_font("ttf"))
        assert up["asset"]["id"]
        prev = post("/api/font_preview", {"asset_id": up["asset"]["id"]})
        assert prev["missing"] == [] and len(prev["shapes"]) == 5
        bad = post("/api/upload?kind=font&name=bad.ttf", b"xxxxxxxxxxxxxxxxxxxxxxxx")
        assert "error" in bad
        lg = post("/api/upload?kind=logo&name=l.png", make_logo_png())
        p["logo"]["asset"] = lg["asset"]
        lp = post("/api/logo_preview", {"logo": p["logo"]})
        assert lp["components"] == 2 and lp["mask_png"]
        err = post("/api/generate", {"project": {**p, "numbers": {**p["numbers"], "depth_mm": -1}}})
        assert "Engraving depth" in err["error"]
        saved = post("/api/save", {"project": p})
        opened = post("/api/open", {"path": saved["path"]})
        assert opened["project"]["logo"]["asset"]["id"] == lg["asset"]["id"]
        ex = post("/api/export", {"project": p, "which": "dice", "die": "d6", "directory": str(tmp_path / "out")})
        assert ex["report"]["ok"]
        assert (tmp_path / "out" / "MySet_D6.stl").exists()
    finally:
        srv.shutdown()
