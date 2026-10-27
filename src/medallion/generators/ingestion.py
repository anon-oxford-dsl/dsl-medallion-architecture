"""Ingestion back-end: a runnable script loading declared CSV sources into their layer.

The artefact is an executable Python script rather than a bare ``.sql`` file so the
generated Airflow DAG has something to invoke, and so all four artefacts share one
database file.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from ..frontend.model import Spec
from .base import GeneratedFile, Generator


class IngestionGenerator(Generator):
    name = "ingestion"
    description = "DuckDB CSV ingestion script for the layers that declare `load`"
    supports = {"database": "duckdb"}  # noqa: RUF012

    def generate(self, spec: Spec) -> list[GeneratedFile]:
        loads = [
            {
                "schema": layer.schema,
                "table": source_name,
                "path": spec.source(source_name).path,
                # Columns are selected by name rather than with `COPY` or `SELECT *`
                # so the load is bound to the declared schema and not to the column
                # order of the file.
                "columns": [column.name for column in spec.source(source_name).columns],
            }
            for layer in spec.topological_layers()
            for source_name in layer.load
        ]
        content = self.render(
            "load_bronze.py.j2",
            product=spec.product,
            database=spec.targets.path,
            loads=loads,
        )
        return [GeneratedFile(PurePosixPath("ingestion/load_bronze.py"), content)]
