"""Tests for agent/main-agent/scripts/render_graph.py.

render_graph turns a validated GraphSpec into a deterministic, themed Plotly
figure. The agent supplies only data + labels; the script owns all styling, so
the same spec must always render byte-identical figure JSON.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO_ROOT / "agent" / "main-agent" / "scripts"
_RENDER = _SCRIPTS / "render_graph.py"


def _load_render():
    spec = importlib.util.spec_from_file_location("_render_graph", _RENDER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _line_spec() -> dict:
    return {
        "id": "return-vs-steps",
        "kind": "line",
        "title": "Mean return vs steps",
        "x_label": "env steps",
        "y_label": "mean return",
        "series": [
            {"name": "ppo+icm", "x": [0, 250000, 500000], "y": [0.0, 0.4, 0.82],
             "error_y": [0.0, 0.05, 0.03]},
            {"name": "baseline", "x": [0, 250000, 500000], "y": [0.0, 0.3, 0.55]},
        ],
    }


def test_build_figure_line_has_a_trace_per_series():
    render = _load_render()
    fig = render.build_figure(render.GraphSpec.model_validate(_line_spec()))
    assert len(fig.data) == 2
    assert fig.data[0].name == "ppo+icm"
    assert fig.layout.title.text == "Mean return vs steps"
    assert fig.layout.xaxis.title.text == "env steps"
    assert fig.layout.yaxis.title.text == "mean return"


def test_error_y_becomes_error_bars():
    render = _load_render()
    fig = render.build_figure(render.GraphSpec.model_validate(_line_spec()))
    assert fig.data[0].error_y.array == (0.0, 0.05, 0.03)
    # second series had no error_y -> no error bars set
    assert not getattr(fig.data[1].error_y, "array", None)


def test_bar_kind_uses_bar_traces():
    render = _load_render()
    spec = _line_spec()
    spec["kind"] = "bar"
    fig = render.build_figure(render.GraphSpec.model_validate(spec))
    assert fig.data[0].type == "bar"


def test_render_is_deterministic():
    render = _load_render()
    g = render.GraphSpec.model_validate(_line_spec())
    assert render.build_figure(g).to_json() == render.build_figure(g).to_json()


def test_cli_writes_rendered_figure_json(tmp_path):
    specs = tmp_path / "specs"
    specs.mkdir()
    spec_file = specs / "return-vs-steps.json"
    spec_file.write_text(json.dumps(_line_spec()))

    proc = subprocess.run(
        [sys.executable, str(_RENDER), str(spec_file)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr

    out = tmp_path / "rendered" / "return-vs-steps.json"
    assert out.exists(), f"expected rendered figure at {out}; stderr={proc.stderr}"
    fig = json.loads(out.read_text())
    assert "data" in fig and "layout" in fig  # a real Plotly figure dict
    assert len(fig["data"]) == 2


def test_bar_with_categorical_x_renders():
    render = _load_render()
    spec = {
        "id": "delta", "kind": "bar", "title": "Δ vs baseline",
        "series": [{"name": "delta", "x": ["ppo+icm", "rnd"], "y": [0.27, 0.05]}],
    }
    fig = render.build_figure(render.GraphSpec.model_validate(spec))
    assert fig.data[0].type == "bar"
    assert tuple(fig.data[0].x) == ("ppo+icm", "rnd")


def test_cross_process_determinism(tmp_path):
    # Same spec rendered in two separate processes must be byte-identical.
    specs = tmp_path / "specs"
    specs.mkdir()
    f = specs / "g.json"
    f.write_text(json.dumps(_line_spec()))
    a, b = tmp_path / "a", tmp_path / "b"
    for out in (a, b):
        proc = subprocess.run(
            [sys.executable, str(_RENDER), str(f), "--out-dir", str(out)],
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
    # output is named by spec.id, not the spec filename
    assert (a / "return-vs-steps.json").read_text() == (b / "return-vs-steps.json").read_text()


def test_cli_rejects_malformed_spec(tmp_path):
    specs = tmp_path / "specs"
    specs.mkdir()
    bad = specs / "bad.json"
    bad.write_text(json.dumps({"id": "bad", "kind": "line", "title": "x", "series": []}))

    proc = subprocess.run(
        [sys.executable, str(_RENDER), str(bad)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 0
    assert not (tmp_path / "rendered" / "bad.json").exists()
