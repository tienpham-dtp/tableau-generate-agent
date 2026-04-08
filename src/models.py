"""Pydantic models for the worksheet_spec contract between Agent 1 and Agent 2."""

from __future__ import annotations

from pydantic import BaseModel


class DatasourceSpec(BaseModel):
    type: str = "snowflake"
    account: str
    database: str
    schema_name: str  # serialized as "schema" in JSON output
    warehouse: str
    table_name: str  # primary table or view the worksheets derive from

    def model_dump(self, **kwargs):
        d = super().model_dump(**kwargs)
        d["schema"] = d.pop("schema_name")
        return d


class FilterSpec(BaseModel):
    field: str
    value: str


class WorksheetDef(BaseModel):
    title: str
    chart_type: str  # bar, line, pie, scatter, area, heatmap
    x_axis: str
    y_axis: str
    color: str | None = None
    filters: list[FilterSpec] = []
    sql: str


class WorksheetSpec(BaseModel):
    """The full contract passed from Agent 1 to Agent 2."""

    datasource: DatasourceSpec
    worksheets: list[WorksheetDef]
