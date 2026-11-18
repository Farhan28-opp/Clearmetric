"""Isolated DuckDB execution.

Each query runs in a fresh in-memory DuckDB connection that can only see one registered Arrow table
named `data`. External file access is disabled and configuration is locked before any compiled SQL
runs, a wall-clock timeout interrupts long queries, and results are bounded. SQL passed here is always
produced by ClearMetric's compiler from validated plans; values are bound as parameters."""
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.dataset.storage import parquet_path

_CACHE: "OrderedDict[str, pa.Table]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 6


def load_table(parquet_key: str) -> pa.Table:
    """Parquet files are immutable per key, so caching by key is safe."""
    with _CACHE_LOCK:
        if parquet_key in _CACHE:
            _CACHE.move_to_end(parquet_key)
            return _CACHE[parquet_key]
    table = pq.read_table(parquet_path(parquet_key))
    with _CACHE_LOCK:
        _CACHE[parquet_key] = table
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return table


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    duration_ms: int


def _connect(table: pa.Table) -> duckdb.DuckDBPyConnection:
    s = get_settings()
    con = duckdb.connect(":memory:", config={"threads": s.duckdb_threads, "memory_limit": s.duckdb_memory_limit})
    con.register("data", table)
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con


def run_sql(parquet_key: str, sql: str, params: list | None = None, timeout: float | None = None,
            max_rows: int | None = None) -> QueryResult:
    s = get_settings()
    timeout = timeout or s.query_timeout_seconds
    table = load_table(parquet_key)
    con = _connect(table)
    timer = threading.Timer(timeout, con.interrupt)
    started = time.perf_counter()
    timer.start()
    try:
        cur = con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(max_rows) if max_rows else cur.fetchall()
    except duckdb.InterruptException:
        raise AppError(408, "query_timeout", f"The calculation exceeded the {timeout:.0f}s time limit")
    except duckdb.Error as e:
        if "INTERRUPT" in str(e).upper():
            raise AppError(408, "query_timeout", f"The calculation exceeded the {timeout:.0f}s time limit")
        raise AppError(422, "execution_error", f"The calculation could not be executed: {str(e).splitlines()[0][:300]}")
    finally:
        timer.cancel()
        con.close()
    return QueryResult(cols, rows, int((time.perf_counter() - started) * 1000))


def quote_ident(name: str) -> str:
    """Identifiers come from validated schema metadata ([a-z0-9_]); quoting is defence in depth."""
    if not name or not all(c.isalnum() or c == "_" for c in name):
        raise AppError(400, "invalid_identifier", "Invalid column reference")
    return '"' + name.replace('"', '""') + '"'
