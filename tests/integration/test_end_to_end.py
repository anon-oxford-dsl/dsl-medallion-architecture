"""Deployment test: the four artefacts must compose into one working pipeline.

Every other deployment suite verifies one artefact in isolation. This one runs
the sequence a real deployment follows -- apply the DDL, run the generated
ingestion script, then invoke dbt -- all against the single database the
specification declares, and checks the data is there at the end.

Run with the dbt environment: ``uv run --group dbt pytest -m dbt``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

duckdb = pytest.importorskip("duckdb", reason="duckdb is not installed in this environment")
DBT = shutil.which("dbt")

pytestmark = [
    pytest.mark.dbt,
    pytest.mark.skipif(
        DBT is None,
        reason="dbt is not installed; run with `uv run --group dbt pytest -m dbt`",
    ),
]


@pytest.fixture
def deployed(deployment, tmp_path, examples_root):
    """A full copy of the generated product, ready to be run in place."""
    spec, out_dir = deployment("customer_orders")
    product_dir = tmp_path / spec.product
    shutil.copytree(out_dir, product_dir)
    return spec, product_dir, examples_root


def test_ddl_then_ingestion_then_dbt_share_one_database(deployed):
    spec, product_dir, examples_root = deployed
    database = product_dir / spec.targets.path

    # 1. Deploy the schema. The DDL is applied once, outside the DAG.
    con = duckdb.connect(str(database))
    con.execute((product_dir / "schema" / "ddl.sql").read_text(encoding="utf-8"))
    con.close()

    # 2. Ingest, exactly as the generated DAG's run_ingestion task does.
    ingest = subprocess.run(
        [
            sys.executable,
            str(product_dir / "ingestion" / "load_bronze.py"),
            "--source-root",
            str(examples_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ingest.returncode == 0, f"ingestion failed:\n{ingest.stdout}\n{ingest.stderr}"

    # 3. Transform, as each layer task does.
    dbt_project = product_dir / "dbt"
    build = subprocess.run(
        [DBT, "build", "--project-dir", str(dbt_project), "--profiles-dir", str(dbt_project)],
        capture_output=True,
        text=True,
        cwd=str(dbt_project),
        check=False,
    )
    assert build.returncode == 0, f"dbt build failed:\n{build.stdout}\n{build.stderr}"

    # The ingestion script defaulted to the product database, and dbt resolved
    # its profile to the same file: exactly one database exists.
    assert [p.name for p in product_dir.glob("*.duckdb")] == [spec.targets.path]

    # 4. The data survives the whole sequence, in the mapped schema.
    con = duckdb.connect(str(database), read_only=True)
    try:
        bronze = next(layer for layer in spec.layers if layer.has_tables)
        count = con.execute(f'select count(*) from "{bronze.schema}"."orders"').fetchone()[0]
        assert count == 5
        schemas = {
            row[0]
            for row in con.execute(
                "select schema_name from duckdb_schemas() where not internal"
            ).fetchall()
        }
        assert {layer.schema for layer in spec.layers} <= schemas
    finally:
        con.close()


def test_dbt_reads_the_ingested_rows_through_its_source(deployed):
    """dbt must resolve `source()` to the table the ingestion script populated."""
    spec, product_dir, examples_root = deployed
    database = product_dir / spec.targets.path

    con = duckdb.connect(str(database))
    con.execute((product_dir / "schema" / "ddl.sql").read_text(encoding="utf-8"))
    con.close()
    subprocess.run(
        [
            sys.executable,
            str(product_dir / "ingestion" / "load_bronze.py"),
            "--source-root",
            str(examples_root),
        ],
        capture_output=True,
        check=True,
    )

    dbt_project = product_dir / "dbt"
    # A user-written model is what the framework deliberately does not generate,
    # so write one here to prove the scaffold it does generate is usable.
    bronze = next(layer for layer in spec.layers if layer.has_tables)
    model = dbt_project / "models" / "silver" / "orders_clean.sql"
    model.write_text(
        f"select order_id, customer_id, amount\nfrom {{{{ source('{bronze.name}', 'orders') }}}}\n",
        encoding="utf-8",
    )

    build = subprocess.run(
        [DBT, "build", "--project-dir", str(dbt_project), "--profiles-dir", str(dbt_project)],
        capture_output=True,
        text=True,
        cwd=str(dbt_project),
        check=False,
    )
    assert build.returncode == 0, f"dbt build failed:\n{build.stdout}\n{build.stderr}"

    silver = next(layer for layer in spec.layers if layer.name == "silver")
    con = duckdb.connect(str(database), read_only=True)
    try:
        rows = con.execute(f'select count(*) from "{silver.schema}"."orders_clean"').fetchone()[0]
    finally:
        con.close()
    assert rows == 5
