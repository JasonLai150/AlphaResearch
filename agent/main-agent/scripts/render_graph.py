#!/usr/bin/env python3
"""Render a validated GraphSpec into a deterministic, themed Plotly figure.

The main agent writes declarative GraphSpec JSON (data + labels + a chart kind)
to ``.graphs/specs/<id>.json``; this script turns it into a beautiful Plotly
figure and writes the figure JSON to ``.graphs/rendered/<id>.json`` for the
frontend (plotly.js) to consume directly.

Determinism by construction: the agent supplies ONLY content. Every styling
choice — template, colorway, fonts, layout, trace uids — lives here, so the same
spec always renders the same figure. No Date/random anywhere.

Usage:
    render_graph.py <spec.json> [--out-dir DIR]

Exit codes:
  0 = rendered (figure JSON written)
  2 = bad arguments
  3 = spec failed GraphSpec validation (nothing written)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plotly.graph_objects as go  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from schemas import GraphKind, GraphSpec  # noqa: E402

# --- the single source of truth for "beautiful" (deterministic) -------------
_TEMPLATE = "plotly_white"
# A fixed, colorblind-friendly palette; series get colors by index, so order in
# the spec -> color is stable across renders.
_COLORWAY = [
    "#2563eb", "#dc2626", "#16a34a", "#d97706",
    "#7c3aed", "#0891b2", "#db2777", "#65a30d",
]
_FONT = {"family": "Inter, -apple-system, Segoe UI, Helvetica, Arial, sans-serif", "size": 14}


def _trace(kind: GraphKind, series, idx: int):
    color = _COLORWAY[idx % len(_COLORWAY)]
    err = {"type": "data", "array": series.error_y, "visible": True} if series.error_y else None
    common = {"name": series.name, "x": series.x, "y": series.y, "uid": f"s{idx}"}
    if kind is GraphKind.bar:
        return go.Bar(**common, marker_color=color, error_y=err)
    mode = "markers" if kind is GraphKind.scatter else "lines+markers"
    return go.Scatter(**common, mode=mode, line={"color": color, "width": 2},
                      marker={"color": color, "size": 6}, error_y=err)


def build_figure(spec: GraphSpec) -> go.Figure:
    """GraphSpec -> a fully themed Plotly Figure. Pure; no I/O, no randomness."""
    fig = go.Figure([_trace(spec.kind, s, i) for i, s in enumerate(spec.series)])
    fig.update_layout(
        template=_TEMPLATE,
        colorway=_COLORWAY,
        font=_FONT,
        title={"text": spec.title, "x": 0.5, "xanchor": "center"},
        xaxis_title=spec.x_label,
        yaxis_title=spec.y_label,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02,
                "xanchor": "right", "x": 1},
        margin={"l": 70, "r": 30, "t": 80, "b": 60},
        barmode="group" if spec.kind is GraphKind.bar else None,
    )
    if spec.caption:
        fig.add_annotation(text=spec.caption, showarrow=False, xref="paper", yref="paper",
                           x=0, y=-0.18, align="left", font={"size": 11, "color": "#6b7280"})
    return fig


def render(spec_path: Path, out_dir: Path | None = None) -> Path:
    """Validate + render one spec file; return the written figure path.

    Raises ValidationError if the spec is malformed (caller maps to exit 3)."""
    spec = GraphSpec.model_validate_json(spec_path.read_text())
    fig = build_figure(spec)
    if out_dir is None:
        # specs live in .graphs/specs/ -> render siblings into .graphs/rendered/
        parent = spec_path.parent
        out_dir = (parent.parent if parent.name == "specs" else parent) / "rendered"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{spec.id}.json"
    out.write_text(fig.to_json())
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Render a GraphSpec into Plotly figure JSON.")
    ap.add_argument("spec", type=Path, help="path to a GraphSpec .json file")
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args(argv)

    if not args.spec.is_file():
        print(f"render_graph: no such spec file: {args.spec}", file=sys.stderr)
        return 2
    try:
        out = render(args.spec, args.out_dir)
    except (ValidationError, ValueError, json.JSONDecodeError) as err:
        print(f"render_graph: invalid GraphSpec ({args.spec}): {err}", file=sys.stderr)
        return 3
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
