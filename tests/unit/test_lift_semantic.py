"""Semantic rejection tests: the checks JSON Schema cannot express."""

from __future__ import annotations

import pytest

from medallion.frontend.errors import SpecValidationError


def _errors(lift_yaml, text):
    with pytest.raises(SpecValidationError) as excinfo:
        lift_yaml(text)
    return excinfo.value.errors


def test_load_references_undeclared_source(lift_yaml):
    errors = _errors(
        lift_yaml,
        """
        product: p
        sources:
          orders: {format: csv, path: o.csv, columns: {id: integer}}
        layers:
          bronze: {load: [ordurs]}
        orchestration: {schedule: "@daily"}
        targets: {database: duckdb, orchestrator: airflow}
        """,
    )
    (error,) = errors
    assert error.path == "layers.bronze.load[0]"
    assert "undeclared source 'ordurs'" in error.message
    assert error.hint and "orders" in error.hint
    assert error.line is not None


def test_depends_on_references_unknown_layer(lift_yaml):
    errors = _errors(
        lift_yaml,
        """
        product: p
        sources:
          orders: {format: csv, path: o.csv, columns: {id: integer}}
        layers:
          bronze: {load: [orders]}
          silver: {depends_on: [brnze]}
        orchestration: {schedule: "@daily"}
        targets: {database: duckdb, orchestrator: airflow}
        """,
    )
    (error,) = errors
    assert error.path == "layers.silver.depends_on[0]"
    assert "unknown layer 'brnze'" in error.message
    assert error.line is not None


def test_dependency_cycle_is_reported_with_path(lift_yaml):
    errors = _errors(
        lift_yaml,
        """
        product: p
        sources:
          orders: {format: csv, path: o.csv, columns: {id: integer}}
        layers:
          bronze: {load: [orders], depends_on: [gold]}
          silver: {depends_on: [bronze]}
          gold: {depends_on: [silver]}
        orchestration: {schedule: "@daily"}
        targets: {database: duckdb, orchestrator: airflow}
        """,
    )
    assert any(e.path == "layers" and e.message.startswith("dependency cycle:") for e in errors)
    cycle_error = next(e for e in errors if e.message.startswith("dependency cycle:"))
    assert "bronze" in cycle_error.message and "->" in cycle_error.message


def test_nothing_ingested_is_reported(lift_yaml):
    errors = _errors(
        lift_yaml,
        """
        product: p
        sources:
          orders: {format: csv, path: o.csv, columns: {id: integer}}
        layers:
          bronze: {}
          silver: {depends_on: [bronze]}
        orchestration: {schedule: "@daily"}
        targets: {database: duckdb, orchestrator: airflow}
        """,
    )
    assert any("nothing would be ingested" in e.message for e in errors)


def test_unknown_column_type_is_rejected_with_helpful_list(lift_yaml):
    errors = _errors(
        lift_yaml,
        """
        product: p
        sources:
          orders: {format: csv, path: o.csv, columns: {amount: money}}
        layers:
          bronze: {load: [orders]}
        orchestration: {schedule: "@daily"}
        targets: {database: duckdb, orchestrator: airflow}
        """,
    )
    assert any(
        e.path == "sources.orders.columns.amount" and e.hint and "decimal" in e.hint for e in errors
    )


def test_multiple_semantic_errors_are_collected(lift_yaml):
    errors = _errors(
        lift_yaml,
        """
        product: p
        sources:
          orders: {format: csv, path: o.csv, columns: {id: integer}}
        layers:
          bronze: {load: [missing_src]}
          silver: {depends_on: [ghost]}
        orchestration: {schedule: "@daily"}
        targets: {database: duckdb, orchestrator: airflow}
        """,
    )
    paths = {e.path for e in errors}
    assert "layers.bronze.load[0]" in paths
    assert "layers.silver.depends_on[0]" in paths


def test_two_layers_cannot_share_a_schema(lift_yaml):
    errors = _errors(
        lift_yaml,
        """
        product: p
        sources:
          orders: {format: csv, path: o.csv, columns: {id: integer}}
        layers:
          bronze: {schema: raw, load: [orders]}
          silver: {schema: raw, depends_on: [bronze]}
        orchestration: {schedule: "@daily"}
        targets: {database: duckdb, orchestrator: airflow}
        """,
    )
    (error,) = errors
    assert error.path == "layers.silver.schema"
    assert "already used by layer 'bronze'" in error.message
    assert error.line is not None


def test_an_implicit_schema_can_collide_with_an_explicit_one(lift_yaml):
    """`schema` defaults to the layer name, so `raw` and a layer named `raw` clash."""
    errors = _errors(
        lift_yaml,
        """
        product: p
        sources:
          orders: {format: csv, path: o.csv, columns: {id: integer}}
        layers:
          raw: {load: [orders]}
          silver: {schema: raw, depends_on: [raw]}
        orchestration: {schedule: "@daily"}
        targets: {database: duckdb, orchestrator: airflow}
        """,
    )
    assert any("already used by layer 'raw'" in e.message for e in errors)
