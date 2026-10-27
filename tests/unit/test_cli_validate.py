from __future__ import annotations

from medallion.cli import main


def test_validate_ok_returns_zero(capsys, example_spec_path):
    rc = main(["validate", str(example_spec_path)])
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_validate_reports_located_error_and_exits_2(tmp_path, capsys):
    spec = tmp_path / "broken.yml"
    spec.write_text(
        "product: p\n"
        "sources:\n"
        "  orders: {format: csv, path: o.csv, columns: {id: integer}}\n"
        "layers:\n"
        "  bronze: {load: [orders]}\n"
        "  silver: {depends_on: [nope]}\n"
        'orchestration: {schedule: "@daily"}\n'
        "targets: {database: duckdb, orchestrator: airflow}\n"
    )
    rc = main(["validate", str(spec)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "broken.yml" in err
    assert "unknown layer 'nope'" in err


def test_validate_missing_file_exits_2(tmp_path, capsys):
    rc = main(["validate", str(tmp_path / "absent.yml")])
    assert rc == 2
    assert "no such file" in capsys.readouterr().err


def test_generate_nests_artefacts_under_the_product(tmp_path, example_spec_path):
    rc = main(["generate", str(example_spec_path), "--out", str(tmp_path)])
    assert rc == 0
    product_dir = tmp_path / "customer_orders"
    written = {str(p.relative_to(product_dir)) for p in product_dir.rglob("*") if p.is_file()}
    assert "schema/ddl.sql" in written
    assert "ingestion/load_bronze.py" in written
    assert "orchestration/dags/customer_orders_dag.py" in written
    assert "dbt/dbt_project.yml" in written


def test_two_products_share_an_output_root_without_colliding(tmp_path, examples_dir):
    for name in ("customer_orders", "minimal"):
        assert main(["generate", str(examples_dir / f"{name}.yml"), "--out", str(tmp_path)]) == 0
    assert (tmp_path / "customer_orders" / "dbt" / "dbt_project.yml").exists()
    assert (tmp_path / "pageviews" / "dbt" / "dbt_project.yml").exists()


def test_generate_only_runs_named_generators(tmp_path, example_spec_path):
    rc = main(["generate", str(example_spec_path), "--out", str(tmp_path), "--only", "schema"])
    assert rc == 0
    product_dir = tmp_path / "customer_orders"
    written = {str(p.relative_to(product_dir)) for p in product_dir.rglob("*") if p.is_file()}
    assert written == {"schema/ddl.sql"}


def test_generate_rejects_unknown_generator(tmp_path, capsys, example_spec_path):
    rc = main(["generate", str(example_spec_path), "--out", str(tmp_path), "--only", "nope"])
    assert rc == 2
    assert "unknown generator" in capsys.readouterr().err


def test_generate_refuses_an_invalid_spec(tmp_path, capsys):
    spec = tmp_path / "bad.yml"
    spec.write_text("product: p\n")
    rc = main(["generate", str(spec), "--out", str(tmp_path / "out")])
    assert rc == 2
    assert "required" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()
