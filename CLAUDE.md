# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
A two-agent AI pipeline that connects to a Snowflake data source, generates chart previews for user review, and produces a single Tableau workbook (`.twb`) containing multiple ready-to-use worksheets. The user's only responsibility is arranging the worksheets into a final dashboard inside Tableau Desktop.

**MVP cap:** 8 worksheets per workbook run.

## Environment

- Python 3.13
- Virtual environment: `.venv/`
- Activate: `source .venv/bin/activate`

## Commands

```bash
source .venv/bin/activate
pip install -e .                # install deps
cp .env.example .env            # fill in Snowflake + Anthropic creds
python -m src.main              # run the full pipeline
```

---

## Agents

### Agent 1 — Data Analyst & Visualization Advisor
- **Input:** Snowflake connection config (account, database, schema, warehouse)
- **Tools:** snowflake-python-connector (schema exploration + data sampling), matplotlib or plotly (local chart rendering)
- **Task:**
  1. Connect to Snowflake and explore the schema (tables, columns, types)
  2. Propose meaningful metrics and KPIs with SQL expressions
  3. [PAUSE] User reviews proposed metrics and SQL logic, selects which ones to proceed with
  4. Fetch a single sample of 5,000 rows total from Snowflake — shared across all selected metrics
  5. For each selected metric, derive chart data from the sample and render a preview chart locally
  6. Present each chart to the user one at a time for approval
  7. After all charts are reviewed, present a confirmation summary listing approved and rejected charts
  8. User can type "Go back" to re-review a specific chart before confirming
- **Human loop:** Two pause points — metric selection after schema exploration, and per-chart approval followed by a final confirmation summary
- **Approval flow:**
  ```
  # Pass 1 — schema + metric proposal
  connect to Snowflake via snowflake-python-connector
  explore schema → propose metrics + SQL
  [PAUSE] user selects which metrics to proceed with

  # Pass 2 — sample once, render all
  fetch 5,000 rows total from Snowflake (shared across all selected metrics)
  for each selected metric:
      derive chart data from the sample
      render chart locally (matplotlib/plotly)
      show to user → approve or reject

  present summary:
      "User has chosen these graphs:
       * Total sales trend line
       * Pie chart for client distribution
       * Gantt chart for sales flow
       The visualizations that were removed are:
       * Customer segmentation bar chart
       Please confirm whether this is correct"

  user types "Go back" → re-enter loop at specified chart
  user confirms → output worksheet_spec
  ```
- **Note:** For MVP, all selected metrics are assumed to derive from a single table or pre-joined view. This keeps the 5,000 row sample unambiguous.
- **Output:** `worksheet_spec` — a JSON object containing only approved charts, plus the shared datasource config

### Agent 2 — Worksheet Generator
- **Input:** `worksheet_spec` from Agent 1
- **Tools:** None — trusts field names and types from the worksheet spec
- **Task:** Generate a single valid `.twb` XML file with one shared `<datasource>` block and one `<worksheet>` block per approved chart. Embed Snowflake connection config into the TWB so Tableau Desktop can connect. Tableau Desktop handles authentication when the user opens the file.
- **Human loop:** None during generation. User reviews output in Tableau Desktop.
- **Output:** `workbook.twb` — one file, all approved worksheets inside

---

## Worksheet Spec (Agent 1 → Agent 2 contract)

```json
{
  "datasource": {
    "type": "snowflake",
    "account": "my-account.snowflakecomputing.com",
    "database": "SALES",
    "schema": "PUBLIC",
    "warehouse": "COMPUTE_WH"
  },
  "worksheets": [
    {
      "title": "Revenue by region",
      "chart_type": "bar",
      "x_axis": "region",
      "y_axis": "SUM(revenue)",
      "color": null,
      "filters": [{ "field": "year", "value": "2024" }],
      "sql": "SELECT region, SUM(revenue) FROM orders WHERE year=2024 GROUP BY region"
    }
  ]
}
```

---

## Orchestration Flow

```
1. Connect to Snowflake    → via snowflake-python-connector, credentials as environment variables
2. Run Agent 1 pass 1      → explores schema, proposes metrics + SQL
3. [PAUSE] User selects    → user picks which metrics to proceed with
4. Run Agent 1 pass 2      → fetches 5,000 rows once, renders all charts, user approves or rejects
5. [PAUSE] Confirm         → Agent 1 presents approved/rejected summary, user confirms or goes back
6. Run Agent 2             → produces workbook.twb
7. Open Tableau Desktop    → user opens .twb, authenticates to Snowflake, arranges worksheets into dashboard
```

Agents communicate via JSON passed by the orchestrator — not directly with each other.

---

## Snowflake Connectivity

- **Library:** `snowflake-python-connector` — no MCP server required
- **Used by:** Agent 1 only (schema exploration + 5,000 row sample fetch)
- **Agent 2:** No Snowflake connection needed — works entirely from the worksheet spec
- **Tableau Desktop:** Connects to Snowflake directly when the user opens the `.twb` file. Credentials are not embedded — Tableau prompts the user to authenticate on first open.
- **Setup:** Snowflake credentials stored as environment variables (`SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`)

---

## TWB Output Structure

```
workbook.twb
└── <datasource>          ← Snowflake connection config, defined once
└── <worksheet> ×N        ← one per approved chart, all sharing the datasource
```

---

## Out of Scope for MVP

| Constraint | Extension path |
|---|---|
| Max 8 worksheets | Chunk into multiple Agent 2 runs, merge TWB XML |
| Single table or pre-joined view | Multi-table sampling with per-table row budgets |
| Tableau Desktop only | Tableau Server/Cloud publish via REST API |
| Tableau only | Power BI via PBIX template + Push Dataset API |
| Snowflake only | Support additional sources via their connectors |
| No dashboard layout | Optional: auto-tiled starter dashboard post-MVP |