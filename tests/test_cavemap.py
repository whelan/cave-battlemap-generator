"""Smoke tests: the example specs parse and pass QA, a small cave renders, walls and the DD plan come out."""
import json
from pathlib import Path

import pytest

from cavemap import dd, render
from cavemap import spec as cavespec

EX = Path(__file__).resolve().parents[1] / "examples"


@pytest.mark.parametrize("name", ["small-cave.yaml", "dragon-lair.yaml"])
def test_examples_pass_qa(name, capsys):
    assert render.main([str(EX / name), "--check"]) == 0
    assert "0 FAIL, 0 WARN" in capsys.readouterr().out


def test_render_small_cave(tmp_path):
    rc = render.main([str(EX / "small-cave.yaml"), "--px", "24", "--out-dir", str(tmp_path), "--dm",
                      "--preview", str(tmp_path / "prev.png"), "--steps", str(tmp_path / "steps")])
    assert rc == 0
    from PIL import Image
    assert Image.open(tmp_path / "small-cave.webp").size == (20 * 24, 16 * 24)
    assert (tmp_path / "small-cave-dm.webp").exists()
    assert sorted(p.name for p in (tmp_path / "steps").iterdir()) == [f"step-{k}.png" for k in range(1, 8)]
    doc = json.loads((tmp_path / "small-cave-foundry.json").read_text())
    assert doc["grid"]["size"] == 24 and doc["walls"] and doc["lights"]


def test_same_seed_same_cave(tmp_path):
    for d in ("a", "b"):
        render.main([str(EX / "small-cave.yaml"), "--px", "16", "--out-dir", str(tmp_path / d)])
    assert (tmp_path / "a/small-cave.webp").read_bytes() == (tmp_path / "b/small-cave.webp").read_bytes()


def test_unreachable_chamber_fails(tmp_path, capsys):
    p = tmp_path / "bad.yaml"
    p.write_text("name: Bad\nsize: [20, 12]\nchambers:\n  - {id: a, at: [4, 6], r: 3}\n  - {id: b, at: [15, 6], r: 3}\n")
    assert render.main([str(p), "--check"]) == 1
    assert "no 5-ft-wide path" in capsys.readouterr().out


def test_markdown_fence(tmp_path):
    p = tmp_path / "note.md"
    p.write_text("# A cave\n\n```cave\n" + (EX / "small-cave.yaml").read_text() + "```\n")
    assert cavespec.normalise(cavespec.read_fence(p))["name"] == "Small Cave"


def test_dd_plan(capsys):
    assert dd.main([str(EX / "dragon-lair.yaml"), "--plan"]) == 0
    assert "objects" in capsys.readouterr().out


def test_dd_build_with_fake_index(tmp_path, monkeypatch):
    from cavemap import ddassets as A
    monkeypatch.setattr(A, "pick", lambda pat, missing=None: "res://packs/FAKE/textures/x.png")
    monkeypatch.setattr(A, "dims", lambda res: (256, 256))
    monkeypatch.setattr(A, "pack_meta", lambda pid: None)
    monkeypatch.setattr(A, "active_packs", lambda: [])
    out = tmp_path / "cave.dungeondraft_map"
    assert dd.main([str(EX / "small-cave.yaml"), "--out", str(out)]) == 0
    lv = json.loads(out.read_text())["world"]["levels"]["0"]
    assert lv["objects"] and lv["walls"] and lv["lights"]
    assert lv["terrain"]["splat"].count(",") + 1 == 20 * 4 * 16 * 4 * 4
