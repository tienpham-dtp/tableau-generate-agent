"""Generate a valid Tableau .twb XML file from a WorksheetSpec.

Uses a real Tableau-generated TWB as a template for the datasource/metadata,
then programmatically adds worksheet and window elements.
"""

from __future__ import annotations

import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from src.models import WorksheetDef, WorksheetSpec

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "tableau_examples" / "tableau_snowflake_example.twb"

# Tableau mark classes for each chart type
_MARK_CLASS = {
    "bar": "Bar",
    "line": "Line",
    "pie": "Pie",
    "scatter": "Circle",
    "area": "Area",
    "heatmap": "Square",
}


def _parse_aggregation(expr: str) -> tuple[str, str]:
    """Parse 'SUM(revenue)' -> ('Sum', 'REVENUE'). Plain 'revenue' -> ('Sum', 'REVENUE')."""
    m = re.match(r"(\w+)\((\w+)\)", expr.strip())
    if m:
        agg_raw, field = m.group(1), m.group(2)
        return agg_raw.capitalize(), field.upper()
    return "Sum", expr.strip().upper()


def _instance_name(name: str, role: str, aggregation: str | None) -> str:
    if role == "dimension":
        return f"[none:{name}:nk]"
    agg = (aggregation or "Sum").lower()
    return f"[{agg}:{name}:qk]"


def _make_uuid() -> str:
    return "{" + str(uuid.uuid4()).upper() + "}"


def generate_twb(
    spec: WorksheetSpec,
    column_types: dict[str, str] | None = None,
) -> str:
    """Build a .twb XML string from a WorksheetSpec.

    Uses the Snowflake TWB template for datasource metadata, then adds
    worksheets and windows programmatically.

    Args:
        spec: The worksheet specification from Agent 1.
        column_types: Optional mapping of column_name -> Snowflake data type.
            Currently unused (template provides metadata).

    Returns:
        A complete .twb XML string ready to write to disk.
    """
    tree = ET.parse(TEMPLATE_PATH)
    root = tree.getroot()

    # Discover the datasource name from the template
    ds_name = _find_datasource_name(root)

    # Remove existing worksheets, windows, thumbnails
    for tag in ["worksheets", "windows", "thumbnails"]:
        el = root.find(tag)
        if el is not None:
            root.remove(el)

    # Add worksheets
    ws_container = ET.SubElement(root, "worksheets")
    for ws_def in spec.worksheets:
        _add_worksheet(ws_container, ws_def, ds_name)

    # Add windows (required by Tableau)
    _add_windows(root, spec.worksheets)

    ET.indent(root, space="  ")
    return "<?xml version='1.0' encoding='utf-8' ?>\n" + ET.tostring(
        root, encoding="unicode"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_datasource_name(root: ET.Element) -> str:
    """Find the main (non-Parameters) datasource name in the template."""
    for ds in root.findall(".//datasources/datasource"):
        name = ds.get("name", "")
        if name != "Parameters" and ds.get("hasconnection") != "false":
            return name
    raise ValueError("No datasource found in template TWB")


def _add_worksheet(
    ws_container: ET.Element,
    ws_def: WorksheetDef,
    ds_name: str,
) -> None:
    """Add a single worksheet element."""
    ws = ET.SubElement(ws_container, "worksheet")
    ws.set("name", ws_def.title)

    table = ET.SubElement(ws, "table")
    view = ET.SubElement(table, "view")

    # Datasource reference
    ds_refs = ET.SubElement(view, "datasources")
    ds_ref = ET.SubElement(ds_refs, "datasource")
    ds_ref.set("name", ds_name)

    # Dependencies
    deps = ET.SubElement(view, "datasource-dependencies")
    deps.set("datasource", ds_name)

    x_name = ws_def.x_axis.upper()
    y_agg, y_name = _parse_aggregation(ws_def.y_axis)

    # Collect fields: (name, role, datatype, aggregation)
    fields = [
        (x_name, "dimension", "string", None),
        (y_name, "measure", "integer", y_agg),
    ]
    if ws_def.color:
        fields.append((ws_def.color.upper(), "dimension", "string", None))

    # Columns first, then column-instances (Tableau ordering)
    for name, role, datatype, _agg in fields:
        col = ET.SubElement(deps, "column")
        col.set("datatype", datatype)
        col.set("name", f"[{name}]")
        col.set("role", role)
        col.set("type", "nominal" if role == "dimension" else "quantitative")

    for name, role, _dt, agg in fields:
        ci = ET.SubElement(deps, "column-instance")
        ci.set("column", f"[{name}]")
        ci.set("derivation", "None" if role == "dimension" else (agg or "Sum"))
        ci.set("name", _instance_name(name, role, agg))
        ci.set("pivot", "key")
        ci.set("type", "nominal" if role == "dimension" else "quantitative")

    # Aggregation (required by Tableau inside <view>)
    agg_el = ET.SubElement(view, "aggregation")
    agg_el.set("value", "true")

    # Style
    ET.SubElement(table, "style")

    # Panes
    panes = ET.SubElement(table, "panes")
    pane = ET.SubElement(panes, "pane")
    pane.set("selection-relaxation-option", "selection-relaxation-allow")
    pane_view = ET.SubElement(pane, "view")
    bd = ET.SubElement(pane_view, "breakdown")
    bd.set("value", "auto")
    mark = ET.SubElement(pane, "mark")
    mark.set("class", _MARK_CLASS.get(ws_def.chart_type, "Automatic"))

    x_inst = _instance_name(x_name, "dimension", None)
    y_inst = _instance_name(y_name, "measure", y_agg)

    # Encodings
    if ws_def.chart_type == "pie":
        encodings = ET.SubElement(pane, "encodings")
        color_enc = ET.SubElement(encodings, "color")
        color_enc.set("column", f"[{ds_name}].{x_inst}")
        wedge = ET.SubElement(encodings, "wedge-size")
        wedge.set("column", f"[{ds_name}].{y_inst}")
    elif ws_def.color:
        c_name = ws_def.color.upper()
        c_inst = _instance_name(c_name, "dimension", None)
        encodings = ET.SubElement(pane, "encodings")
        color_enc = ET.SubElement(encodings, "color")
        color_enc.set("column", f"[{ds_name}].{c_inst}")

    # Rows and cols
    rows = ET.SubElement(table, "rows")
    cols = ET.SubElement(table, "cols")
    if ws_def.chart_type == "pie":
        pass  # empty for pie
    else:
        rows.text = f"[{ds_name}].{y_inst}"
        cols.text = f"[{ds_name}].{x_inst}"

    # simple-id (required)
    sid = ET.SubElement(ws, "simple-id")
    sid.set("uuid", _make_uuid())


def _add_windows(root: ET.Element, worksheets: list[WorksheetDef]) -> None:
    """Add the <windows> section (required by Tableau)."""
    windows = ET.SubElement(root, "windows")
    windows.set("source-height", "30")

    for i, ws_def in enumerate(worksheets):
        window = ET.SubElement(windows, "window")
        window.set("class", "worksheet")
        if i == 0:
            window.set("maximized", "true")
        window.set("name", ws_def.title)

        cards = ET.SubElement(window, "cards")

        edge_left = ET.SubElement(cards, "edge")
        edge_left.set("name", "left")
        strip_left = ET.SubElement(edge_left, "strip")
        strip_left.set("size", "160")
        for ct in ["pages", "filters", "marks"]:
            card = ET.SubElement(strip_left, "card")
            card.set("type", ct)

        edge_top = ET.SubElement(cards, "edge")
        edge_top.set("name", "top")
        for sz, ct in [("2147483647", "columns"), ("2147483647", "rows"), ("31", "title")]:
            strip = ET.SubElement(edge_top, "strip")
            strip.set("size", sz)
            card = ET.SubElement(strip, "card")
            card.set("type", ct)

        sid = ET.SubElement(window, "simple-id")
        sid.set("uuid", _make_uuid())
