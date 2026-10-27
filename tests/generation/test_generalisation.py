"""The generators follow the declared graph, not hard-coded bronze/silver/gold.

These are the cases that demonstrate the layer model is general and that
`bronze`/`silver`/`gold` is a convention, not a rule.
"""

from __future__ import annotations

from medallion.generators import generate_all
from medallion.generators.ingestion import IngestionGenerator
from medallion.generators.orchestration import OrchestrationGenerator
from medallion.generators.scaffold import ScaffoldGenerator
from medallion.generators.schema_ddl import SchemaGenerator

DIAMOND = """
product: telemetry
sources:
  events: {format: csv, path: raw/events/*.csv, columns: {id: bigint, ts: timestamp}}
  devices: {format: csv, path: raw/devices/*.csv, columns: {id: bigint, label: string}}
layers:
  landing: {load: [events, devices]}
  clean_events: {depends_on: [landing]}
  clean_devices: {depends_on: [landing]}
  marts: {depends_on: [clean_events, clean_devices]}
orchestration: {schedule: "@hourly", start_date: "2025-03-01"}
targets: {database: duckdb, orchestrator: airflow}
"""


def test_arbitrary_layer_names_drive_the_ddl(lift_yaml):
    spec = lift_yaml(DIAMOND)
    ddl = SchemaGenerator().generate(spec)[0].content
    for layer in ("landing", "clean_events", "clean_devices", "marts"):
        assert f'CREATE SCHEMA IF NOT EXISTS "{layer}";' in ddl
    # Only the ingesting layer gets tables; derived layers are schema-only.
    assert 'CREATE TABLE IF NOT EXISTS "landing"."events"' in ddl
    assert 'CREATE TABLE IF NOT EXISTS "landing"."devices"' in ddl
    assert 'clean_events"."' not in ddl
    assert 'marts"."' not in ddl


def test_schemas_precede_the_tables_and_layers_that_need_them(lift_yaml):
    ddl = SchemaGenerator().generate(lift_yaml(DIAMOND))[0].content
    assert ddl.index('SCHEMA IF NOT EXISTS "landing"') < ddl.index('"landing"."events"')
    assert ddl.index('SCHEMA IF NOT EXISTS "landing"') < ddl.index('SCHEMA IF NOT EXISTS "marts"')


def test_multiple_sources_each_get_a_load_entry(lift_yaml):
    script = IngestionGenerator().generate(lift_yaml(DIAMOND))[0].content
    assert '"landing",\n        "events",\n        "raw/events/*.csv",' in script
    assert '"landing",\n        "devices",\n        "raw/devices/*.csv",' in script
    # Columns are named so the load binds to the declared schema, not file order.
    assert '["id", "ts"]' in script
    assert '["id", "label"]' in script


def test_ingestion_artefact_is_an_executable_script(lift_yaml):
    files = IngestionGenerator().generate(lift_yaml(DIAMOND))
    assert str(files[0].path) == "ingestion/load_bronze.py"
    script = files[0].content
    assert script.startswith("#!/usr/bin/env python3")
    assert "def main(" in script and "duckdb.connect" in script
    # The database is resolved relative to the script, never as an absolute path.
    assert "PRODUCT_DIR / " in script


def test_ingestion_task_feeds_only_the_layers_that_load(lift_yaml):
    dag = OrchestrationGenerator().generate(lift_yaml(DIAMOND))[0].content
    assert "task_run_ingestion >> task_landing" in dag
    # Derived layers are fed by their upstream layer, not by ingestion directly.
    for derived in ("clean_events", "clean_devices", "marts"):
        assert f"task_run_ingestion >> task_{derived}" not in dag


def test_dbt_command_is_selectable(lift_yaml):
    spec = lift_yaml(
        DIAMOND.replace('schedule: "@hourly"', 'schedule: "@hourly", dbt_command: run')
    )
    dag = OrchestrationGenerator().generate(spec)[0].content
    assert "dbt run --select landing" in dag
    assert "dbt build" not in dag


def test_dag_reproduces_a_diamond_dependency_graph(lift_yaml):
    dag = OrchestrationGenerator().generate(lift_yaml(DIAMOND))[0].content
    for layer in ("landing", "clean_events", "clean_devices", "marts"):
        assert f'task_id="{layer}",' in dag
    assert "task_landing >> task_clean_events" in dag
    assert "task_landing >> task_clean_devices" in dag
    assert "task_clean_events >> task_marts" in dag
    assert "task_clean_devices >> task_marts" in dag
    assert 'schedule="@hourly"' in dag
    assert "datetime.datetime(2025, 3, 1)" in dag


def test_dag_filename_follows_the_product(lift_yaml):
    files = OrchestrationGenerator().generate(lift_yaml(DIAMOND))
    assert str(files[0].path) == "orchestration/dags/telemetry_dag.py"


def test_scaffold_creates_a_model_dir_per_layer(lift_yaml):
    files = generate_all(lift_yaml(DIAMOND))["scaffold"]
    paths = {str(f.path) for f in files}
    for layer in ("landing", "clean_events", "clean_devices", "marts"):
        assert f"dbt/models/{layer}/.gitkeep" in paths
    # Model directories are empty: no transformation SQL is ever generated.
    assert not any(str(f.path).endswith(".sql") and "/models/" in str(f.path) for f in files)


def test_single_layer_product_has_no_dependency_edges(lift_yaml):
    spec = lift_yaml(
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
    dag = OrchestrationGenerator().generate(spec)[0].content
    # No layer-to-layer edges, but ingestion still feeds the single layer.
    assert dag.count(">>") == 1
    assert "task_run_ingestion >> task_only" in dag
    assert 'task_id="only",' in dag


def test_all_abstract_types_map_to_duckdb(lift_yaml):
    spec = lift_yaml(
        """
        product: types_probe
        sources:
          wide:
            format: csv
            path: w.csv
            columns:
              c_integer: integer
              c_bigint: bigint
              c_decimal: decimal
              c_double: double
              c_float: float
              c_string: string
              c_boolean: boolean
              c_date: date
              c_timestamp: timestamp
              c_time: time
        layers:
          raw: {load: [wide]}
        orchestration: {schedule: "@daily"}
        targets: {database: duckdb, orchestrator: airflow}
        """
    )
    ddl = SchemaGenerator().generate(spec)[0].content
    for column, duck in [
        ("c_integer", "INTEGER"),
        ("c_bigint", "BIGINT"),
        ("c_decimal", "DECIMAL(18,2)"),
        ("c_double", "DOUBLE"),
        ("c_float", "FLOAT"),
        ("c_string", "VARCHAR"),
        ("c_boolean", "BOOLEAN"),
        ("c_date", "DATE"),
        ("c_timestamp", "TIMESTAMP"),
        ("c_time", "TIME"),
    ]:
        assert f'"{column}" {duck}' in ddl


# The diagram's own case: medallion layer names mapped onto different schemas.
MAPPED_SCHEMAS = """
product: sales_analytics
sources:
  orders: {format: csv, path: raw/orders/*.csv, columns: {id: integer}}
layers:
  bronze: {schema: raw, load: [orders]}
  silver: {schema: clean, depends_on: [bronze]}
  gold: {schema: analytics, depends_on: [silver]}
orchestration: {schedule: "0 6 * * *"}
targets: {database: duckdb, orchestrator: airflow}
"""


def test_ddl_uses_the_mapped_schema_not_the_layer_name(lift_yaml):
    ddl = SchemaGenerator().generate(lift_yaml(MAPPED_SCHEMAS))[0].content
    for schema in ("raw", "clean", "analytics"):
        assert f'CREATE SCHEMA IF NOT EXISTS "{schema}";' in ddl
    for layer in ("bronze", "silver", "gold"):
        assert f'CREATE SCHEMA IF NOT EXISTS "{layer}";' not in ddl
    assert 'CREATE TABLE IF NOT EXISTS "raw"."orders"' in ddl


def test_ingestion_targets_the_mapped_schema(lift_yaml):
    script = IngestionGenerator().generate(lift_yaml(MAPPED_SCHEMAS))[0].content
    assert '"raw",\n        "orders",' in script


def test_dag_task_ids_keep_the_layer_names(lift_yaml):
    """Layer name is identity; `schema` is only physical placement."""
    dag = OrchestrationGenerator().generate(lift_yaml(MAPPED_SCHEMAS))[0].content
    for layer in ("bronze", "silver", "gold"):
        assert f'task_id="{layer}",' in dag
    assert 'task_id="raw",' not in dag


def test_dbt_scaffold_maps_directories_to_schemas(lift_yaml):
    files = {
        str(f.path): f.content for f in ScaffoldGenerator().generate(lift_yaml(MAPPED_SCHEMAS))
    }
    project = files["dbt/dbt_project.yml"]
    # Directory keeps the layer name; +schema places the models.
    assert '    bronze:\n      +schema: "raw"' in project
    assert "dbt/models/bronze/.gitkeep" in files
    # The dbt source is named for the layer but points at the mapped schema.
    sources = files["dbt/models/sources.yml"]
    assert "- name: bronze" in sources
    assert "schema: raw" in sources


def test_all_artefacts_point_at_one_database(lift_yaml):
    spec = lift_yaml(MAPPED_SCHEMAS)
    profiles = {str(f.path): f.content for f in ScaffoldGenerator().generate(spec)}[
        "dbt/profiles.yml"
    ]
    script = IngestionGenerator().generate(spec)[0].content
    # dbt resolves its path from <product>/dbt/; the script from <product>/ingestion/.
    assert 'path: "../sales_analytics.duckdb"' in profiles
    assert 'DEFAULT_DATABASE = PRODUCT_DIR / "sales_analytics.duckdb"' in script
