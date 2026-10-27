"""The measurement harness used to report framework metrics.

These tests pin the *definitions* of the metrics, so a reported number cannot
silently change meaning.
"""

from __future__ import annotations

import json

import pytest

from medallion.cli import main
from medallion.frontend.lift import lift
from medallion.frontend.parse import parse_spec_file
from medallion.metrics import DagMetrics, LineCounts, collect, render_json, render_table

# --------------------------------------------------------------------------- line counting


def test_line_counts_split_sql_into_blank_comment_and_code():
    counts = LineCounts.of("-- header\n\nSELECT 1;\nSELECT 2;\n", ".sql")
    assert counts == LineCounts(total=4, blank=1, comment=1, code=2)


def test_line_counts_treat_yaml_hashes_as_comments():
    counts = LineCounts.of("# note\nproduct: p\n\nlayers: {}\n", ".yml")
    assert counts == LineCounts(total=4, blank=1, comment=1, code=2)


def test_line_counts_treat_python_docstrings_as_comments():
    text = '"""Module docstring\nspanning two lines.\n"""\n\nimport os  # trailing\n'
    counts = LineCounts.of(text, ".py")
    assert counts.comment == 3  # the docstring, not the trailing comment's line
    assert counts.code == 1
    assert counts.blank == 1


def test_line_counts_of_a_file_type_without_comment_syntax():
    assert LineCounts.of("a\nb\n", ".gitkeep").comment == 0


def test_line_counts_add():
    assert LineCounts(1, 1, 1, 1) + LineCounts(2, 2, 2, 2) == LineCounts(3, 3, 3, 3)


# --------------------------------------------------------------------------- dag complexity


def test_dag_metrics_for_a_linear_medallion_chain(example_spec):
    """run_ingestion -> bronze -> silver -> gold: the graph actually emitted."""
    dag = DagMetrics.of(example_spec)
    assert dag.task_count == 4  # three layers plus the ingestion task
    assert dag.dependency_edges == 3
    assert dag.max_depth == 4
    assert dag.root_tasks == 1  # run_ingestion
    assert dag.leaf_tasks == 1  # gold
    # 3 edges of the 6 a 4-node DAG could have.
    assert dag.density == pytest.approx(3 / 6, abs=1e-4)
    # McCabe on the task graph: E - V + 2.
    assert dag.cyclomatic_complexity == 1


def test_dag_metrics_for_a_diamond(lift_yaml):
    dag = DagMetrics.of(
        lift_yaml(
            """
            product: t
            sources:
              e: {format: csv, path: e.csv, columns: {id: bigint}}
            layers:
              landing: {load: [e]}
              a: {depends_on: [landing]}
              b: {depends_on: [landing]}
              marts: {depends_on: [a, b]}
            orchestration: {schedule: "@daily"}
            targets: {database: duckdb, orchestrator: airflow}
            """
        )
    )
    # landing/a/b/marts plus run_ingestion; ingestion feeds only `landing`.
    assert (dag.task_count, dag.dependency_edges, dag.max_depth) == (5, 5, 4)
    assert dag.root_tasks == 1 and dag.leaf_tasks == 1
    assert dag.cyclomatic_complexity == 2


def test_dag_metrics_for_a_single_task(lift_yaml):
    dag = DagMetrics.of(
        lift_yaml(
            """
            product: solo
            sources:
              t: {format: csv, path: t.csv, columns: {a: integer}}
            layers:
              only: {load: [t]}
            orchestration: {schedule: "@daily"}
            targets: {database: duckdb, orchestrator: airflow}
            """
        )
    )
    # Even a one-layer product has an ingestion task upstream of it.
    assert (dag.task_count, dag.dependency_edges, dag.max_depth) == (2, 1, 2)
    assert dag.density == pytest.approx(1.0)  # the only possible edge is present


# --------------------------------------------------------------------------- report


def test_report_measures_the_specification_and_its_output(example_spec, example_spec_path):
    report = collect(example_spec, example_spec_path)

    assert report.scenario == "customer_orders"
    assert report.product == "customer_orders"
    assert (report.source_count, report.layer_count, report.column_count) == (1, 3, 3)

    # Specification: every non-blank, non-comment line.
    assert report.spec_lines.code > 0
    assert report.spec_lines.total == (
        report.spec_lines.code + report.spec_lines.comment + report.spec_lines.blank
    )

    # Output is measured the same way, so the ratio compares like with like.
    assert report.generated_lines.code > report.spec_lines.code
    assert report.expansion_ratio == pytest.approx(
        report.generated_lines.code / report.spec_lines.code, abs=0.01
    )


def test_report_covers_every_generator_and_file(example_spec, example_spec_path):
    report = collect(example_spec, example_spec_path)
    assert [m.name for m in report.generators] == [
        "schema",
        "ingestion",
        "orchestration",
        "scaffold",
    ]
    assert report.file_count == sum(m.file_count for m in report.generators) == 10
    assert report.generated_bytes == sum(m.bytes for m in report.generators)


def test_report_is_stable(example_spec, example_spec_path):
    assert collect(example_spec, example_spec_path) == collect(example_spec, example_spec_path)


def test_larger_scenario_generates_more(examples_dir):
    def report_for(name):
        path = examples_dir / name
        return collect(lift(parse_spec_file(path), source=str(path)), path)

    minimal = report_for("minimal.yml")
    retail = report_for("retail_analytics.yml")

    assert minimal.dag.task_count < retail.dag.task_count
    assert minimal.file_count < retail.file_count
    assert minimal.generated_lines.code < retail.generated_lines.code


# --------------------------------------------------------------------------- rendering / CLI


def test_json_is_machine_readable(example_spec, example_spec_path):
    payload = json.loads(render_json([collect(example_spec, example_spec_path)]))
    assert isinstance(payload, list) and len(payload) == 1
    record = payload[0]
    assert record["scenario"] == "customer_orders"
    assert record["dag"]["task_count"] == 4
    assert record["expansion_ratio"] > 1
    assert record["spec_lines"]["code"] > 0


def test_table_lists_a_row_per_scenario(example_spec, example_spec_path):
    text = render_table([collect(example_spec, example_spec_path)])
    assert "scenario" in text and "customer_orders" in text
    for generator in ("schema", "ingestion", "orchestration", "scaffold"):
        assert generator in text


def test_cli_metrics_table(capsys, example_spec_path):
    assert main(["metrics", str(example_spec_path)]) == 0
    assert "customer_orders" in capsys.readouterr().out


def test_cli_metrics_accepts_several_scenarios(capsys, examples_dir):
    rc = main(
        [
            "metrics",
            str(examples_dir / "minimal.yml"),
            str(examples_dir / "retail_analytics.yml"),
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert [record["scenario"] for record in payload] == ["minimal", "retail_analytics"]


def test_cli_metrics_rejects_an_invalid_spec(tmp_path, capsys):
    bad = tmp_path / "bad.yml"
    bad.write_text("product: p\n")
    assert main(["metrics", str(bad)]) == 2
    assert "required" in capsys.readouterr().err
