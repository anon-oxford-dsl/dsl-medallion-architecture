"""Schema back-end: DuckDB DDL for the layer hierarchy."""

from __future__ import annotations

from pathlib import PurePosixPath

from ..frontend.model import Spec
from .base import GeneratedFile, Generator
from .types import duckdb_type


class SchemaGenerator(Generator):
    name = "schema"
    description = "DuckDB DDL: a schema per layer, tables for ingested sources"
    supports = {"database": "duckdb"}  # noqa: RUF012

    def generate(self, spec: Spec) -> list[GeneratedFile]:
        layers = [
            {
                "name": layer.schema,
                "tables": [
                    {
                        "name": source_name,
                        "columns": [
                            {"name": column.name, "type": duckdb_type(column.type)}
                            for column in spec.source(source_name).columns
                        ],
                    }
                    for source_name in layer.load
                ],
            }
            for layer in spec.topological_layers()
        ]
        content = self.render("ddl.sql.j2", product=spec.product, layers=layers)
        return [GeneratedFile(PurePosixPath("schema/ddl.sql"), content)]
