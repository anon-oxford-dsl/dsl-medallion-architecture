"""Scaffold back-end: a dbt project skeleton.

Model directories are created for every layer and left empty. The transformation
SQL is the user's to write; generating it is out of scope by design.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from ..frontend.model import Spec
from .base import GeneratedFile, Generator
from .types import dbt_data_type


class ScaffoldGenerator(Generator):
    name = "scaffold"
    description = "dbt project: dbt_project.yml, profiles.yml, sources.yml, empty model dirs"
    supports = {"database": "duckdb"}  # noqa: RUF012

    def generate(self, spec: Spec) -> list[GeneratedFile]:
        ordered = spec.topological_layers()

        project = self.render(
            "dbt_project.yml.j2",
            product=spec.product,
            layers=[
                {
                    # The model directory keeps the layer's name; `+schema` places it.
                    "name": layer.name,
                    "schema": layer.schema,
                    # Ingested layers land data; derived layers are views by default.
                    "materialized": "table" if layer.has_tables else "view",
                }
                for layer in ordered
            ],
        )
        profiles = self.render(
            "profiles.yml.j2",
            product=spec.product,
            # Relative to the dbt project directory, which is where dbt resolves it,
            # so dbt writes to the same database the ingestion script loads into.
            database=f"../{spec.targets.path}",
        )
        ingesting = [layer for layer in ordered if layer.has_tables]
        sources = self.render(
            "sources.yml.j2",
            product=spec.product,
            # Shown in a comment as a worked source() call.
            example_layer=ingesting[0].name,
            example_table=ingesting[0].load[0],
            sources=[
                {
                    "layer": layer.name,
                    "schema": layer.schema,
                    "tables": [
                        {
                            "name": source_name,
                            "path": spec.source(source_name).path,
                            "columns": [
                                {"name": column.name, "type": dbt_data_type(column.type)}
                                for column in spec.source(source_name).columns
                            ],
                        }
                        for source_name in layer.load
                    ],
                }
                for layer in ingesting
            ],
        )
        schema_macro = self.render("generate_schema_name.sql.j2")

        files = [
            GeneratedFile(PurePosixPath("dbt/dbt_project.yml"), project),
            GeneratedFile(PurePosixPath("dbt/profiles.yml"), profiles),
            GeneratedFile(PurePosixPath("dbt/models/sources.yml"), sources),
            GeneratedFile(PurePosixPath("dbt/macros/generate_schema_name.sql"), schema_macro),
        ]
        files.extend(
            # .gitkeep so the empty directory survives version control.
            GeneratedFile(PurePosixPath(f"dbt/models/{layer.name}/.gitkeep"), "")
            for layer in ordered
        )
        return files
