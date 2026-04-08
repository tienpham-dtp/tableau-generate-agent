"""Agent 1 — Data Analyst & Visualization Advisor.

Uses Claude API with tool use to:
  Pass 1: explore Snowflake schema → propose metrics + SQL
  Pass 2: fetch sample → render charts → collect user approvals
"""

from __future__ import annotations

import json
import sys
from typing import Any

import anthropic

from src.chart_renderer import render_chart
from src.config import SnowflakeConfig
from src.models import DatasourceSpec, FilterSpec, WorksheetDef, WorksheetSpec
from src.snowflake_client import SnowflakeClient

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 16000

# Prompt caching — mark static system/tool content for reuse across turns
_CACHE_CONTROL = {"type": "ephemeral"}

# ---------------------------------------------------------------------------
# Tool definitions (raw JSON schema — used by messages.create)
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_tables",
        "description": "List all tables and views in the configured Snowflake schema.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "describe_table",
        "description": "Get column names, data types, and nullability for a table.",
        "input_schema": {
            "type": "object",
            "properties": {
                "table_name": {
                    "type": "string",
                    "description": "Name of the table to describe.",
                }
            },
            "required": ["table_name"],
        },
    },
    {
        "name": "fetch_sample",
        "description": (
            "Run a SQL query against Snowflake and return up to 5000 rows. "
            "Use this to fetch the shared data sample for chart rendering."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "SQL query to execute.",
                }
            },
            "required": ["sql"],
        },
    },
    {
        "name": "render_chart",
        "description": (
            "Render a chart preview from data. Returns the file path to a PNG image. "
            "Call this once per approved metric to produce a preview for the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "line", "pie", "scatter", "area", "heatmap"],
                    "description": "Type of chart to render.",
                },
                "title": {
                    "type": "string",
                    "description": "Chart title.",
                },
                "x_axis": {
                    "type": "string",
                    "description": "Column name for the x-axis (must exist in data).",
                },
                "y_axis": {
                    "type": "string",
                    "description": "Column name for the y-axis (must exist in data).",
                },
                "data": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Array of row objects to chart. Keep under 500 rows for readability.",
                },
                "color": {
                    "type": ["string", "null"],
                    "description": "Optional column name for color grouping.",
                },
            },
            "required": ["chart_type", "title", "x_axis", "y_axis", "data"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------


def _execute_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    sf_client: SnowflakeClient,
) -> str:
    """Execute a tool call and return the result as a string."""
    if tool_name == "list_tables":
        tables = sf_client.list_tables()
        return json.dumps(tables, indent=2)

    if tool_name == "describe_table":
        cols = sf_client.describe_table(tool_input["table_name"])
        return json.dumps(cols, indent=2)

    if tool_name == "fetch_sample":
        try:
            rows = sf_client.fetch_sample(tool_input["sql"], limit=5000)
        except Exception as e:
            return f"SQL Error: {e}\nFix your query and try again."
        return json.dumps(rows[:20], indent=2, default=str) + (
            f"\n... ({len(rows)} rows total)" if len(rows) > 20 else ""
        )

    if tool_name == "render_chart":
        path = render_chart(
            chart_type=tool_input["chart_type"],
            title=tool_input["title"],
            x_axis=tool_input["x_axis"],
            y_axis=tool_input["y_axis"],
            data=tool_input["data"],
            color=tool_input.get("color"),
        )
        return f"Chart saved to: {path}"

    return f"Unknown tool: {tool_name}"


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_PASS1 = """\
You are a data analyst connected to a Snowflake database. Your task:

1. Use list_tables to discover available tables.
2. Use describe_table on the most relevant tables to understand their columns.
3. Based on the schema, propose 3-8 meaningful metrics/KPIs with:
   - A descriptive title for each
   - The chart type (bar, line, pie, scatter, area)
   - Which columns to use for x-axis and y-axis (use aggregation syntax like SUM(col))
   - Any useful filters
   - The SQL query to fetch the data

IMPORTANT: Text columns that contain numeric values may have commas (e.g. "16,448"). \
Always use REPLACE(col, ',', '')::FLOAT instead of col::FLOAT for casting.

Present your proposals in a numbered list. For each, show:
  Title | Chart Type | X-Axis | Y-Axis | SQL

After presenting all proposals, ask the user which metrics they'd like to proceed with.

DO NOT use fetch_sample or render_chart in this phase. Only explore the schema and propose metrics.\
"""

SYSTEM_PROMPT_PASS2 = """\
You are a data analyst. The user has selected specific metrics to visualize.

IMPORTANT: Text columns that contain numeric values may have commas (e.g. "16,448"). \
Always use REPLACE(col, ',', '')::FLOAT instead of col::FLOAT for casting.

Your task:
1. Use fetch_sample to get data from Snowflake (one query for all metrics if possible, \
or separate queries as needed — stay within 5000 rows total).
2. For each selected metric, derive the chart data from the sample and call render_chart.
3. After rendering each chart, tell the user you saved the chart and ask if they approve it.
4. After all charts are reviewed, present a confirmation summary:
   "Here are the approved charts:
    * [list approved]
   The following were removed:
    * [list rejected]
   Please confirm this is correct, or type 'Go back' to revisit a specific chart."

When the user confirms, output the final worksheet spec as a JSON code block with this exact schema:
```json
{
  "datasource": { ... },
  "worksheets": [ ... ]
}
```

The datasource must include: type, account, database, schema_name, warehouse, table_name.
Each worksheet must include: title, chart_type, x_axis, y_axis, color (or null), filters, sql.\
"""


def _stream_message(
    client: anthropic.Anthropic,
    system_prompt: str,
    messages: list[dict[str, Any]],
) -> anthropic.types.Message:
    """Send a streaming request with adaptive thinking and prompt caching.

    Returns the final assembled Message (same shape as messages.create).
    Streaming prevents timeout on long responses.
    """
    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": _CACHE_CONTROL,
                }
            ],
            tools=TOOLS,
            messages=messages,
        ) as stream:
            return stream.get_final_message()
    except anthropic.RateLimitError:
        print("\nRate limited by the API. Wait a moment and try again.")
        sys.exit(1)
    except anthropic.AuthenticationError:
        print("\nInvalid ANTHROPIC_API_KEY. Check your .env file.")
        sys.exit(1)
    except anthropic.APIStatusError as e:
        print(f"\nAPI error ({e.status_code}): {e.message}")
        sys.exit(1)


def _run_agent_loop(
    client: anthropic.Anthropic,
    sf_client: SnowflakeClient,
    system_prompt: str,
    user_message: str,
) -> str:
    """Run a Claude tool-use loop until end_turn. Returns the final text response."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

    while True:
        response = _stream_message(client, system_prompt, messages)

        # Process the response
        if response.stop_reason == "end_turn":
            text = next(
                (b.text for b in response.content if b.type == "text"), ""
            )
            return text

        # Handle tool use
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        if not tool_use_blocks:
            text = next(
                (b.text for b in response.content if b.type == "text"), ""
            )
            return text

        # Append assistant response (preserve full content for compaction)
        messages.append({"role": "assistant", "content": response.content})

        # Execute tools and collect results
        tool_results = []
        for tool_block in tool_use_blocks:
            result = _execute_tool(tool_block.name, tool_block.input, sf_client)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": result,
                }
            )

        messages.append({"role": "user", "content": tool_results})


def _run_interactive_loop(
    client: anthropic.Anthropic,
    sf_client: SnowflakeClient,
    system_prompt: str,
    initial_message: str,
    max_user_inputs: int | None = None,
) -> str:
    """Run an agent loop with human-in-the-loop pauses.

    The agent runs until it produces text output (end_turn or pause_turn).
    That text is shown to the user. The user's reply is fed back to continue
    the conversation.

    Termination:
      - If max_user_inputs is set, the loop ends after that many user inputs
        and the subsequent agent response.
      - Otherwise, the loop ends when the agent's response contains a JSON
        code block with a worksheet spec.
    """
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": initial_message}
    ]
    user_input_count = 0

    while True:
        response = _stream_message(client, system_prompt, messages)

        # Handle tool calls within the loop
        while response.stop_reason == "tool_use":
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for tool_block in tool_use_blocks:
                result = _execute_tool(
                    tool_block.name, tool_block.input, sf_client
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": result,
                    }
                )
            messages.append({"role": "user", "content": tool_results})

            response = _stream_message(client, system_prompt, messages)

        # Extract text from the response
        text = next(
            (b.text for b in response.content if b.type == "text"), ""
        )
        messages.append({"role": "assistant", "content": response.content})

        print("\n" + "=" * 60)
        print(text)
        print("=" * 60)

        # Check termination conditions
        if max_user_inputs is not None and user_input_count >= max_user_inputs:
            return text
        if max_user_inputs is None and "```json" in text and '"worksheets"' in text:
            return text

        # Pause for user input
        user_reply = input("\nYour response: ").strip()
        if not user_reply:
            user_reply = "Continue."
        messages.append({"role": "user", "content": user_reply})
        user_input_count += 1


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_agent1(sf_config: SnowflakeConfig) -> WorksheetSpec:
    """Run the full Agent 1 pipeline and return the worksheet spec."""
    client = anthropic.Anthropic()

    with SnowflakeClient(sf_config) as sf_client:
        # Pass 1: schema exploration + metric proposals
        print("\n--- Agent 1 Pass 1: Exploring schema and proposing metrics ---\n")
        pass1_result = _run_interactive_loop(
            client=client,
            sf_client=sf_client,
            system_prompt=SYSTEM_PROMPT_PASS1,
            initial_message=(
                f"Connect to the Snowflake database '{sf_config.database}' "
                f"schema '{sf_config.schema_name}'. "
                "Explore the schema, then propose meaningful metrics and KPIs."
            ),
            max_user_inputs=1,  # end after user selects metrics
        )

        # Extract selected metrics from user interaction
        # Pass 1 ends when the user selects metrics.
        # Pass 2 begins with those selections.
        print("\n--- Agent 1 Pass 2: Rendering charts for approval ---\n")

        pass2_result = _run_interactive_loop(
            client=client,
            sf_client=sf_client,
            system_prompt=SYSTEM_PROMPT_PASS2,
            initial_message=(
                f"The user has reviewed the metric proposals. "
                f"Here is the context from the previous analysis:\n\n{pass1_result}\n\n"
                f"Snowflake connection: database={sf_config.database}, "
                f"schema={sf_config.schema_name}, warehouse={sf_config.warehouse}, "
                f"account={sf_config.account}.\n\n"
                "Now fetch sample data and render chart previews for each selected metric. "
                "Present each chart for approval."
            ),
        )

    # Parse the JSON spec from the final response
    return _extract_spec(pass2_result)


def _extract_spec(text: str) -> WorksheetSpec:
    """Extract the WorksheetSpec JSON from the agent's final text response."""
    # Find JSON between ```json and ```
    start = text.find("```json")
    if start == -1:
        raise ValueError("Agent 1 did not produce a JSON worksheet spec.")
    start = text.index("\n", start) + 1
    end = text.find("```", start)
    if end == -1:
        raise ValueError("Malformed JSON block in Agent 1 output.")

    raw = text[start:end].strip()
    data = json.loads(raw)

    # Normalize schema_name field
    ds = data["datasource"]
    if "schema" in ds and "schema_name" not in ds:
        ds["schema_name"] = ds.pop("schema")

    # Parse into Pydantic models
    return WorksheetSpec(
        datasource=DatasourceSpec(**ds),
        worksheets=[
            WorksheetDef(
                title=w["title"],
                chart_type=w["chart_type"],
                x_axis=w["x_axis"],
                y_axis=w["y_axis"],
                color=w.get("color"),
                filters=[FilterSpec(**f) for f in w.get("filters", [])],
                sql=w["sql"],
            )
            for w in data["worksheets"]
        ],
    )
