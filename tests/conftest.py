from __future__ import annotations

import duckdb
import pytest

from bottleneck_logistics.store.db import init_schema


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    init_schema(c)
    yield c
    c.close()
