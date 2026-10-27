from __future__ import annotations

from medallion.frontend.model import (
    AbstractType,
    Column,
    Orchestration,
    Targets,
)


def test_example_lifts_to_expected_model(example_spec):
    spec = example_spec

    assert spec.product == "customer_orders"

    assert len(spec.sources) == 1
    orders = spec.sources[0]
    assert orders.name == "orders"
    assert orders.format == "csv"
    assert orders.path == "data/raw/orders/*.csv"
    assert orders.columns == (
        Column("order_id", AbstractType.INTEGER),
        Column("customer_id", AbstractType.INTEGER),
        Column("amount", AbstractType.DECIMAL),
    )

    assert spec.layer_names == ("bronze", "silver", "gold")
    assert spec.layer("bronze").load == ("orders",)
    assert spec.layer("bronze").has_tables is True
    assert spec.layer("silver").depends_on == ("bronze",)
    assert spec.layer("silver").has_tables is False
    assert spec.layer("gold").depends_on == ("silver",)

    # The layer name is its identity; `schema` is its physical placement.
    assert [(layer.name, layer.schema) for layer in spec.layers] == [
        ("bronze", "raw"),
        ("silver", "clean"),
        ("gold", "analytics"),
    ]

    assert spec.orchestration == Orchestration(
        schedule="0 6 * * *", start_date="2024-01-01", dbt_command="build"
    )
    assert spec.targets == Targets(
        database="duckdb", orchestrator="airflow", path="customer_orders.duckdb"
    )


def test_optional_fields_default_during_lifting(lift_yaml):
    spec = lift_yaml(
        """
        product: defaults_probe
        sources:
          t: {format: csv, path: t.csv, columns: {a: integer}}
        layers:
          bronze: {load: [t]}
          silver: {depends_on: [bronze]}
        orchestration: {schedule: "@daily"}
        targets: {database: duckdb, orchestrator: airflow}
        """
    )
    # `schema` falls back to the layer name, so every back-end sees a concrete value.
    assert [(layer.name, layer.schema) for layer in spec.layers] == [
        ("bronze", "bronze"),
        ("silver", "silver"),
    ]
    assert spec.orchestration.start_date == "2024-01-01"
    assert spec.orchestration.dbt_command == "build"
    assert spec.targets.path == "defaults_probe.duckdb"


def test_explicit_optional_fields_are_carried_through(lift_yaml):
    spec = lift_yaml(
        """
        product: explicit_probe
        sources:
          t: {format: csv, path: t.csv, columns: {a: integer}}
        layers:
          landing: {schema: raw, load: [t]}
        orchestration: {schedule: "@daily", start_date: "2025-06-01", dbt_command: run}
        targets: {database: duckdb, orchestrator: airflow, path: warehouse.duckdb}
        """
    )
    assert spec.layer("landing").schema == "raw"
    assert spec.orchestration.start_date == "2025-06-01"
    assert spec.orchestration.dbt_command == "run"
    assert spec.targets.path == "warehouse.duckdb"


def test_topological_layers_orders_by_dependency(example_spec):
    assert [layer.name for layer in example_spec.topological_layers()] == [
        "bronze",
        "silver",
        "gold",
    ]


def test_declaration_order_is_preserved(lift_yaml):
    spec = lift_yaml(
        """
        product: p
        sources:
          a: {format: csv, path: a.csv, columns: {x: integer}}
          b: {format: csv, path: b.csv, columns: {y: string}}
        layers:
          raw: {load: [b, a]}
          curated: {depends_on: [raw]}
        orchestration: {schedule: "@daily"}
        targets: {database: duckdb, orchestrator: airflow}
        """
    )
    assert spec.source_names == ("a", "b")
    assert spec.layer("raw").load == ("b", "a")
    assert spec.layer_names == ("raw", "curated")
