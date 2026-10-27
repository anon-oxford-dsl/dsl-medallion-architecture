"""Orchestration back-end: an Airflow DAG mirroring the layer-dependency graph.

The task graph is the ingestion step followed by the layer-dependency graph:
``run_ingestion`` feeds every layer that declares ``load``, and the layer tasks
invoke dbt in dependency order.
"""

from __future__ import annotations

from datetime import date
from pathlib import PurePosixPath

from ..frontend.model import Spec
from .base import GeneratedFile, Generator

#: Task id of the generated ingestion step.
INGESTION_TASK = "run_ingestion"


class OrchestrationGenerator(Generator):
    name = "orchestration"
    description = "Apache Airflow DAG: ingestion, then one dbt task per layer"
    supports = {"orchestrator": "airflow"}  # noqa: RUF012

    def generate(self, spec: Spec) -> list[GeneratedFile]:
        ordered = spec.topological_layers()
        # Emit edges in topological order of the downstream layer so output is stable.
        edges = [
            {"upstream": upstream, "downstream": layer.name}
            for layer in ordered
            for upstream in layer.depends_on
        ]
        # Ingestion feeds exactly the layers it loads into, which keeps non-linear
        # layer graphs correct rather than assuming a single bronze entry point.
        ingested = [layer.name for layer in ordered if layer.has_tables]

        start = date.fromisoformat(spec.orchestration.start_date)
        content = self.render(
            "dag.py.j2",
            product=spec.product,
            schedule=spec.orchestration.schedule,
            dbt_command=spec.orchestration.dbt_command,
            start_year=start.year,
            start_month=start.month,
            start_day=start.day,
            ingestion_task=INGESTION_TASK,
            ingested=ingested,
            layers=[layer.name for layer in ordered],
            edges=edges,
        )
        path = PurePosixPath(f"orchestration/dags/{spec.product}_dag.py")
        return [GeneratedFile(path, content)]
