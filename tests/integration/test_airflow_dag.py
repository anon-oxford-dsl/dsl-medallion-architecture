"""Deployment test: the generated DAG must pass Apache Airflow's own validation.

Run with the Airflow environment: ``uv run --group airflow pytest -m airflow``.

Airflow 3 changed this API: `DagBag` moved to
`airflow.dag_processing.dagbag`, its `include_examples` argument was removed --
example DAGs are excluded via `AIRFLOW__CORE__LOAD_EXAMPLES` in conftest -- and a
timetable's cron string is read from `dag.timetable.expression`.
"""

from __future__ import annotations

import pytest

pytest.importorskip(
    "airflow",
    reason="Apache Airflow is not installed; run with `uv run --group airflow pytest -m airflow`",
)

# Imported after the skip guard above, so a missing Airflow skips rather than errors.
from airflow.dag_processing.dagbag import DagBag

from medallion.generators.orchestration import INGESTION_TASK

pytestmark = pytest.mark.airflow


@pytest.fixture
def dag_for(deployment):
    """Parse a scenario's generated DAG folder through Airflow and return the DAG."""

    def _load(scenario: str):
        spec, out_dir = deployment(scenario)
        bag = DagBag(dag_folder=str(out_dir / "orchestration" / "dags"))
        assert bag.import_errors == {}, f"Airflow failed to import the DAG: {bag.import_errors}"
        assert spec.product in bag.dags, f"expected a DAG named {spec.product}"
        return spec, bag.dags[spec.product]

    return _load


def test_generated_dag_imports_without_errors(dag_for, scenario):
    spec, dag = dag_for(scenario)
    assert dag.dag_id == spec.product


def test_dag_passes_airflow_validation(dag_for, scenario):
    """`DAG.validate()` is Airflow's own structural check, including cycle detection."""
    _, dag = dag_for(scenario)
    dag.validate()


def test_one_task_per_layer_plus_ingestion(dag_for, scenario):
    spec, dag = dag_for(scenario)
    assert {task.task_id for task in dag.tasks} == {INGESTION_TASK, *spec.layer_names}


def test_task_wiring_reproduces_the_layer_dependencies(dag_for, scenario):
    spec, dag = dag_for(scenario)
    expected: dict[str, set[str]] = {name: set() for name in spec.layer_names}
    expected[INGESTION_TASK] = set()
    for layer in spec.layers:
        for upstream in layer.depends_on:
            expected[upstream].add(layer.name)
        if layer.has_tables:
            expected[INGESTION_TASK].add(layer.name)

    actual = {task.task_id: set(task.downstream_task_ids) for task in dag.tasks}
    assert actual == expected


def test_ingestion_runs_before_every_layer_that_loads(dag_for, scenario):
    spec, dag = dag_for(scenario)
    ingestion = dag.get_task(INGESTION_TASK)
    assert set(ingestion.downstream_task_ids) == {
        layer.name for layer in spec.layers if layer.has_tables
    }
    assert not ingestion.upstream_task_ids  # it is the entry point


def test_ingestion_task_invokes_the_generated_script(dag_for, scenario):
    _, dag = dag_for(scenario)
    command = dag.get_task(INGESTION_TASK).bash_command
    assert "ingestion/load_bronze.py" in command
    assert "--source-root" in command


#: Airflow expands its shorthand presets to cron before building a timetable.
CRON_PRESETS = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
}


def test_schedule_is_the_declared_cron_expression(dag_for, scenario):
    spec, dag = dag_for(scenario)
    declared = spec.orchestration.schedule
    expected = CRON_PRESETS.get(declared, declared)
    assert dag.timetable.expression == expected


def test_start_date_and_catchup_are_as_declared(dag_for, scenario):
    spec, dag = dag_for(scenario)
    assert dag.start_date.date().isoformat() == spec.orchestration.start_date
    assert dag.catchup is False


def test_roots_and_leaves_match_the_task_graph(dag_for, scenario):
    spec, dag = dag_for(scenario)
    # Ingestion is the only entry point: every source layer now depends on it.
    downstream = {d for layer in spec.layers for d in layer.depends_on}
    expected_leaves = {layer.name for layer in spec.layers if layer.name not in downstream}

    assert {task.task_id for task in dag.roots} == {INGESTION_TASK}
    assert {task.task_id for task in dag.leaves} == expected_leaves


def test_each_layer_task_invokes_dbt_for_its_own_layer(dag_for, scenario):
    spec, dag = dag_for(scenario)
    command = spec.orchestration.dbt_command
    for task in dag.tasks:
        if task.task_id == INGESTION_TASK:
            continue
        assert f"dbt {command} --select {task.task_id}" in task.bash_command


def test_dag_is_tagged_as_generated(dag_for):
    _, dag = dag_for("customer_orders")
    assert {"medallion", "generated"} <= set(dag.tags)
