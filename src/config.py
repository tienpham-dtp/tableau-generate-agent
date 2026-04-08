from __future__ import annotations

import os

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class SnowflakeConfig(BaseModel):
    account: str
    user: str
    password: str
    warehouse: str
    database: str
    schema_name: str  # "schema" shadows pydantic's .schema()

    @classmethod
    def from_env(cls) -> SnowflakeConfig:
        return cls(
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            user=os.environ["SNOWFLAKE_USER"],
            password=os.environ["SNOWFLAKE_PASSWORD"],
            warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
            database=os.environ["SNOWFLAKE_DATABASE"],
            schema_name=os.environ["SNOWFLAKE_SCHEMA"],
        )
