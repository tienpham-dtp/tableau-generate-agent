"""Orchestrator — entry point for the two-agent pipeline.

Flow:
  1. Load Snowflake config from environment
  2. Run Agent 1 (schema → metrics → charts → user approval → worksheet_spec)
  3. Run Agent 2 (worksheet_spec → workbook.twb)
"""

from __future__ import annotations

import sys

from src.agent1 import run_agent1
from src.agent2 import run_agent2
from src.config import SnowflakeConfig


def main() -> None:
    print("=" * 60)
    print("  Tableau Workbook Generator")
    print("  Snowflake → Chart Previews → .twb")
    print("=" * 60)

    # Step 1: Load config
    try:
        sf_config = SnowflakeConfig.from_env()
    except KeyError as e:
        print(f"\nMissing environment variable: {e}")
        print("Copy .env.example to .env and fill in your Snowflake credentials.")
        sys.exit(1)

    print(f"\nConnecting to: {sf_config.account}")
    print(f"Database: {sf_config.database}.{sf_config.schema_name}")
    print(f"Warehouse: {sf_config.warehouse}")

    # Step 2: Agent 1 — explore, propose, chart, approve
    spec = run_agent1(sf_config)

    print(f"\n--- Worksheet spec ready: {len(spec.worksheets)} worksheets ---")

    # Step 3: Agent 2 — generate .twb
    print("\n--- Agent 2: Generating Tableau workbook ---\n")
    output_path = run_agent2(spec)

    print("\n" + "=" * 60)
    print(f"  Done! Open {output_path} in Tableau Desktop.")
    print("  Tableau will prompt you to authenticate to Snowflake.")
    print("  Arrange the worksheets into your dashboard.")
    print("=" * 60)


if __name__ == "__main__":
    main()
