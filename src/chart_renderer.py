"""Render preview charts using matplotlib. Returns PNG path for user review."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt


CHARTS_DIR = Path("charts")


def render_chart(
    chart_type: str,
    title: str,
    x_axis: str,
    y_axis: str,
    data: list[dict[str, Any]],
    color: str | None = None,
) -> str:
    """Render a chart from data and return the path to the saved PNG.

    Args:
        chart_type: One of bar, line, pie, scatter, area, heatmap.
        title: Chart title.
        x_axis: Column name for x-axis.
        y_axis: Column name for y-axis.
        data: List of row dicts containing x_axis and y_axis keys.
        color: Optional column name for color grouping.

    Returns:
        Path to saved PNG file.
    """
    CHARTS_DIR.mkdir(exist_ok=True)

    x_vals = [row.get(x_axis, "") for row in data]
    y_vals = [_to_float(row.get(y_axis, 0)) for row in data]

    fig, ax = plt.subplots(figsize=(10, 6))

    renderer = _RENDERERS.get(chart_type, _render_bar)
    renderer(ax, x_vals, y_vals, color, data)

    ax.set_title(title, fontsize=14, fontweight="bold")
    if chart_type != "pie":
        ax.set_xlabel(x_axis)
        ax.set_ylabel(y_axis)
        # Rotate x labels if many values
        if len(x_vals) > 6:
            plt.xticks(rotation=45, ha="right")

    plt.tight_layout()

    safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in title)
    path = CHARTS_DIR / f"{safe_title}.png"
    fig.savefig(path, dpi=100)
    plt.close(fig)

    return str(path)


def _to_float(val: Any) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _render_bar(ax, x_vals, y_vals, color, data):
    ax.bar(range(len(x_vals)), y_vals, tick_label=x_vals)


def _render_line(ax, x_vals, y_vals, color, data):
    ax.plot(x_vals, y_vals, marker="o")


def _render_pie(ax, x_vals, y_vals, color, data):
    ax.pie(y_vals, labels=x_vals, autopct="%1.1f%%", startangle=90)
    ax.axis("equal")


def _render_scatter(ax, x_vals, y_vals, color, data):
    x_numeric = [_to_float(v) for v in x_vals]
    ax.scatter(x_numeric, y_vals)


def _render_area(ax, x_vals, y_vals, color, data):
    ax.fill_between(range(len(x_vals)), y_vals, alpha=0.4)
    ax.plot(range(len(x_vals)), y_vals)
    ax.set_xticks(range(len(x_vals)))
    ax.set_xticklabels(x_vals)


def _render_heatmap(ax, x_vals, y_vals, color, data):
    # Fallback: render as bar chart for MVP
    _render_bar(ax, x_vals, y_vals, color, data)


_RENDERERS = {
    "bar": _render_bar,
    "line": _render_line,
    "pie": _render_pie,
    "scatter": _render_scatter,
    "area": _render_area,
    "heatmap": _render_heatmap,
}
