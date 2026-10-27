"""Deployment test: the generated DDL and ingestion script must run on real DuckDB.

Run with the base environment: ``uv run pytest -m duckdb``.

The ingestion artefact is an executable script, so it is driven as a subprocess
rather than imported -- that is how the generated Airflow DAG invokes it, and it
is the honest test of whether the artefact runs.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from medallion.generators.types import duckdb_type

duckdb = pytest.importorskip("duckdb", reason="duckdb is not installed in this environment")

pytestmark = pytest.mark.duckdb


@pytest.fixture
def database(deployment, scenario, tmp_path):
    """A real file database for one scenario, with the generated DDL applied."""
    spec, out_dir = deployment(scenario)
    path = tmp_path / spec.targets.path
    con = duckdb.connect(str(path))
    con.execute((out_dir / "schema" / "ddl.sql").read_text(encoding="utf-8"))
    con.close()
    return path


def _connect(path):
    return duckdb.connect(str(path), read_only=False)


def run_ingestion(out_dir, database, examples_root, *, expect_success=True):
    """Invoke the generated ingestion script exactly as the DAG would."""
    result = subprocess.run(
        [
            sys.executable,
            str(out_dir / "ingestion" / "load_bronze.py"),
            "--database",
            str(database),
            "--source-root",
            str(examples_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if expect_success:
        assert result.returncode == 0, f"ingestion failed:\n{result.stdout}\n{result.stderr}"
    return result


def _schemas(con) -> set[str]:
    return {
        row[0]
        for row in con.execute(
            "select schema_name from duckdb_schemas() where not internal"
        ).fetchall()
    }


def _tables(con) -> set[tuple[str, str]]:
    return {
        (row[0], row[1])
        for row in con.execute(
            "select table_schema, table_name from information_schema.tables"
        ).fetchall()
    }


def test_ddl_creates_the_mapped_schema_for_every_layer(database, deployment, scenario):
    spec, _ = deployment(scenario)
    con = _connect(database)
    try:
        # Schemas are named by `schema`, which defaults to the layer name.
        assert _schemas(con) >= {layer.schema for layer in spec.layers}
    finally:
        con.close()


def test_tables_exist_only_for_layers_that_declare_load(database, deployment, scenario):
    spec, _ = deployment(scenario)
    con = _connect(database)
    try:
        expected = {
            (layer.schema, source_name) for layer in spec.layers for source_name in layer.load
        }
        assert _tables(con) == expected

        # Derived layers exist as schemas but hold nothing: their tables come from
        # the dbt transformations the user writes, and are never invented here.
        derived = {layer.schema for layer in spec.layers if not layer.has_tables}
        assert not {schema for schema, _ in _tables(con)} & derived
    finally:
        con.close()


def test_columns_match_the_declared_types_and_order(database, deployment, scenario):
    spec, _ = deployment(scenario)
    con = _connect(database)
    try:
        for layer in spec.layers:
            for source_name in layer.load:
                source = spec.source(source_name)
                actual = con.execute(
                    "select column_name, data_type from information_schema.columns "
                    "where table_schema = ? and table_name = ? order by ordinal_position",
                    [layer.schema, source_name],
                ).fetchall()
                assert actual == [(c.name, duckdb_type(c.type)) for c in source.columns]
    finally:
        con.close()


def test_generated_script_loads_every_declared_source(
    database, deployment, scenario, examples_root
):
    spec, out_dir = deployment(scenario)
    run_ingestion(out_dir, database, examples_root)

    con = _connect(database)
    try:
        for layer in spec.layers:
            for source_name in layer.load:
                query = f'select count(*) from "{layer.schema}"."{source_name}"'
                assert con.execute(query).fetchone()[0] > 0, f"{layer.schema}.{source_name}"
    finally:
        con.close()


def test_loaded_values_round_trip(deployment, tmp_path, examples_root):
    """The CSV fixture is small and known, so exact values can be asserted."""
    spec, out_dir = deployment("customer_orders")
    path = tmp_path / spec.targets.path
    con = duckdb.connect(str(path))
    con.execute((out_dir / "schema" / "ddl.sql").read_text(encoding="utf-8"))
    con.close()

    run_ingestion(out_dir, path, examples_root)

    con = _connect(path)
    try:
        rows = con.execute(
            "select order_id, customer_id, amount from raw.orders order by order_id"
        ).fetchall()
    finally:
        con.close()
    assert [(r[0], r[1], float(r[2])) for r in rows] == [
        (1, 100, 29.99),
        (2, 100, 15.50),
        (3, 101, 120.00),
        (4, 102, 7.25),
        (5, 101, 42.00),
    ]


def test_ddl_is_idempotent(database, deployment):
    """`IF NOT EXISTS` throughout: re-applying the DDL must not fail."""
    _, out_dir = deployment("customer_orders")
    con = _connect(database)
    try:
        ddl = (out_dir / "schema" / "ddl.sql").read_text(encoding="utf-8")
        con.execute(ddl)
        con.execute(ddl)
        assert ("raw", "orders") in _tables(con)
    finally:
        con.close()


def test_ingestion_appends_rather_than_replacing(deployment, tmp_path, examples_root):
    """Documented limitation: loading twice doubles the rows."""
    spec, out_dir = deployment("customer_orders")
    path = tmp_path / spec.targets.path
    con = duckdb.connect(str(path))
    con.execute((out_dir / "schema" / "ddl.sql").read_text(encoding="utf-8"))
    con.close()

    run_ingestion(out_dir, path, examples_root)
    run_ingestion(out_dir, path, examples_root)

    con = _connect(path)
    try:
        assert con.execute("select count(*) from raw.orders").fetchone()[0] == 10
    finally:
        con.close()


def test_ingestion_fails_clearly_when_the_ddl_was_never_applied(
    deployment, tmp_path, examples_root
):
    """A missing table must be an explanatory failure, not a traceback."""
    spec, out_dir = deployment("customer_orders")
    empty = tmp_path / spec.targets.path  # connected but no DDL applied
    result = run_ingestion(out_dir, empty, examples_root, expect_success=False)

    assert result.returncode == 1
    assert "does not exist" in result.stderr
    assert "ddl.sql" in result.stderr
