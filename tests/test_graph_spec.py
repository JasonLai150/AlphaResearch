"""Unit tests for the GraphSpec schema (agent/main-agent/scripts/schemas.py).

GraphSpec is the declarative contract the main agent writes: data + labels + a
chart kind, nothing about styling. A validation hook gates it and render_graph.py
turns it into a deterministic, themed Plotly figure. These tests pin the contract.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCHEMAS = (
    Path(__file__).resolve().parent.parent
    / "agent" / "main-agent" / "scripts" / "schemas.py"
)


def _load_schemas():
    spec = importlib.util.spec_from_file_location("_main_agent_schemas", _SCHEMAS)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # so pydantic can resolve forward-ref'd annotations
    spec.loader.exec_module(mod)
    return mod


schemas = _load_schemas()
GraphSpec = schemas.GraphSpec


def _valid() -> dict:
    return {
        "id": "ppo-vs-baseline-return",
        "kind": "line",
        "title": "Mean return vs training steps",
        "x_label": "env steps",
        "y_label": "mean return",
        "series": [
            {"name": "ppo+icm", "x": [0, 250000, 500000], "y": [0.0, 0.4, 0.82]},
            {"name": "baseline", "x": [0, 250000, 500000], "y": [0.0, 0.3, 0.55]},
        ],
    }


def test_valid_spec_parses():
    g = GraphSpec.model_validate(_valid())
    assert g.kind == "line"
    assert len(g.series) == 2
    assert g.series[0].name == "ppo+icm"


def test_empty_title_rejected():
    bad = _valid()
    bad["title"] = "   "
    with pytest.raises(ValueError):
        GraphSpec.model_validate(bad)


def test_zero_series_rejected():
    bad = _valid()
    bad["series"] = []
    with pytest.raises(ValueError):
        GraphSpec.model_validate(bad)


def test_mismatched_xy_length_rejected():
    bad = _valid()
    bad["series"][0]["y"] = [0.0, 0.4]  # x has 3, y has 2
    with pytest.raises(ValueError):
        GraphSpec.model_validate(bad)


def test_error_y_length_must_match_y():
    bad = _valid()
    bad["series"][0]["error_y"] = [0.1, 0.1]  # y has 3
    with pytest.raises(ValueError):
        GraphSpec.model_validate(bad)


def test_unknown_kind_rejected():
    bad = _valid()
    bad["kind"] = "pie"  # not in the supported set
    with pytest.raises(ValueError):
        GraphSpec.model_validate(bad)


def test_error_y_optional():
    ok = _valid()
    ok["series"][0]["error_y"] = [0.05, 0.03, 0.02]
    g = GraphSpec.model_validate(ok)
    assert g.series[0].error_y == [0.05, 0.03, 0.02]


def test_categorical_x_allowed_for_bar_charts():
    # The headline use case: per-idea delta bar with idea NAMES on the x-axis.
    spec = {
        "id": "delta", "kind": "bar", "title": "Δ vs baseline",
        "series": [{"name": "delta", "x": ["ppo+icm", "rnd", "dapo"], "y": [0.27, 0.05, 0.12]}],
    }
    g = GraphSpec.model_validate(spec)
    assert g.series[0].x == ["ppo+icm", "rnd", "dapo"]


def test_numeric_x_stays_numeric():
    g = GraphSpec.model_validate(_valid())
    assert all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in g.series[0].x)
