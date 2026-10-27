"""Structural (JSON Schema) rejection tests, all routed through ``lift``."""

from __future__ import annotations

import pytest

from medallion.frontend.errors import SpecValidationError

BASE = """\
product: customer_orders
sources:
  orders:
    format: csv
    path: data/raw/orders/*.csv
    columns:
      order_id: integer
layers:
  bronze:
    load: [orders]
orchestration:
  schedule: "0 6 * * *"
targets:
  database: duckdb
  orchestrator: airflow
"""


def _errors(lift_yaml, text):
    with pytest.raises(SpecValidationError) as excinfo:
        lift_yaml(text)
    return excinfo.value.errors


def test_missing_required_key(lift_yaml):
    text = BASE.replace("product: customer_orders\n", "")
    errors = _errors(lift_yaml, text)
    assert any(e.path == "product" and "required" in e.message for e in errors)


def test_product_must_be_identifier(lift_yaml):
    errors = _errors(lift_yaml, BASE.replace("customer_orders", "Customer Orders"))
    assert any(e.path == "product" and e.hint and "identifier" in e.hint for e in errors)


def test_unknown_source_format_rejected(lift_yaml):
    errors = _errors(lift_yaml, BASE.replace("format: csv", "format: parquet"))
    assert any("csv" in e.message for e in errors)


def test_unexpected_key_rejected(lift_yaml):
    errors = _errors(lift_yaml, BASE.replace("path:", "pathh:"))
    assert any(e.path.startswith("sources.orders") for e in errors)


def test_bad_target_database_rejected(lift_yaml):
    errors = _errors(lift_yaml, BASE.replace("database: duckdb", "database: postgres"))
    assert any(e.path == "targets.database" for e in errors)


def test_errors_carry_source_and_line(lift_yaml):
    errors = _errors(lift_yaml, BASE.replace("format: csv", "format: parquet"))
    located = [e for e in errors if e.line is not None]
    assert located, "structural errors should be located to a line"
