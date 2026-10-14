"""The demo page (scripts/build_site.py): one static HTML file drawn from the demo run's demo.json."""

import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


demo_run = _load("demo_run")
build_site = _load("build_site")


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    folder = tmp_path_factory.mktemp("site") / "demo"
    assert demo_run.main(["--out", str(folder)]) == 0
    return folder / "demo.json"


@pytest.fixture(scope="module")
def page(demo, tmp_path_factory):
    out = tmp_path_factory.mktemp("site") / "index.html"
    assert build_site.main(["--demo", str(demo), "--out", str(out)]) == 0
    return out.read_text(encoding="utf-8")


def test_the_page_shows_every_step_and_its_title(demo, page):
    data = json.loads(demo.read_text(encoding="utf-8"))
    for step in data["steps"]:
        assert f'id="step-{step["id"]}"' in page
        assert build_site.esc(step["title"]) in page
        assert f'href="#step-{step["id"]}"' in page  # the at-a-glance strip links to it


def test_the_page_shows_the_end_states_and_the_renamed_header(page):
    for status in ("finished", "deleted"):
        assert f"tone-{build_site.STATUS_TONE[status]}\">{status}" in page
    assert 'class="cell old">On hand' in page
    assert 'class="cell new">Quantity on hand' in page


def test_the_page_is_static_and_self_contained(page):
    assert "<script" not in page.lower()
    assert not re.search(r"""(src|href)\s*=\s*["']https?://""", page)
    assert "@import" not in page and "url(" not in page


def test_the_same_run_gives_the_same_page(demo, tmp_path):
    first, second = tmp_path / "one.html", tmp_path / "two.html"
    assert build_site.main(["--demo", str(demo), "--out", str(first)]) == 0
    assert build_site.main(["--demo", str(demo), "--out", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()


def test_text_from_the_record_is_escaped():
    html = build_site.build({"steps": [{"id": "x", "title": "<b>bold</b> & co", "story": "a < b", "calls": []}],
                             "people": [], "company": {}, "after": {}})
    assert "&lt;b&gt;bold&lt;/b&gt; &amp; co" in html
    assert "<b>bold</b>" not in html


def test_a_missing_demo_file_fails_with_a_message(tmp_path, capsys):
    assert build_site.main(["--demo", str(tmp_path / "none.json"), "--out", str(tmp_path / "x.html")]) == 1
    assert "no demo.json" in capsys.readouterr().err
