"""Agent 2 — Worksheet Generator.

Pure Python: takes a WorksheetSpec and produces a .twb file.
No AI calls needed — the spec fully determines the output.
"""

from __future__ import annotations

from pathlib import Path

from src.models import WorksheetSpec
from src.twb_generator import generate_twb


OUTPUT_DIR = Path("output")


def run_agent2(
    spec: WorksheetSpec,
    column_types: dict[str, str] | None = None,
    output_path: Path | None = None,
) -> Path:
    """Generate a .twb file from the worksheet spec.

    Args:
        spec: Validated WorksheetSpec from Agent 1.
        column_types: Optional Snowflake column type mapping for accurate
            Tableau datatypes. If None, types are inferred from field usage.
        output_path: Where to write the .twb. Defaults to output/workbook.twb.

    Returns:
        Path to the generated .twb file.
    """
    if output_path is None:
        OUTPUT_DIR.mkdir(exist_ok=True)
        output_path = OUTPUT_DIR / "workbook.twb"

    twb_xml = generate_twb(spec, column_types=column_types)
    output_path.write_text(twb_xml, encoding="utf-8")

    print(f"\nWorkbook written to: {output_path}")
    print(f"  Datasource: {spec.datasource.database}.{spec.datasource.schema_name}")
    print(f"  Table: {spec.datasource.table_name}")
    print(f"  Worksheets: {len(spec.worksheets)}")
    for ws in spec.worksheets:
        print(f"    - {ws.title} ({ws.chart_type})")

    return output_path
