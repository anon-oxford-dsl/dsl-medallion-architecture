"""The typed internal model: the single source of truth every generator consumes.

These dataclasses are produced only by :func:`medallion.frontend.lift.lift`. They are
frozen and hold no untyped ``dict`` state: once you have a :class:`Spec`, the YAML,
the JSON Schema and the semantic rules are all behind you.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .graph import topological_order


# `str, Enum` rather than `StrEnum`, which needs Python 3.11; this keeps the 3.10 floor.
class AbstractType(str, Enum):  # noqa: UP042
    """Database-agnostic column types. Concrete mappings live in ``generators/types.py``."""

    INTEGER = "integer"
    BIGINT = "bigint"
    DECIMAL = "decimal"
    DOUBLE = "double"
    FLOAT = "float"
    STRING = "string"
    BOOLEAN = "boolean"
    DATE = "date"
    TIMESTAMP = "timestamp"
    TIME = "time"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass(frozen=True)
class Column:
    name: str
    type: AbstractType


@dataclass(frozen=True)
class Source:
    name: str
    format: str  # only "csv" in v1
    path: str
    columns: tuple[Column, ...]


@dataclass(frozen=True)
class Layer:
    """One medallion layer.

    ``name`` is the layer's identity -- it names the DAG task and the dbt model
    directory. ``schema`` is only its physical placement in the database, and is
    resolved to the layer name during lifting when the spec omits it.
    """

    name: str
    schema: str
    load: tuple[str, ...] = ()  # names of sources ingested into this layer
    depends_on: tuple[str, ...] = ()  # names of upstream layers

    @property
    def has_tables(self) -> bool:
        """True when the schema generator should emit ``CREATE TABLE`` for this layer."""
        return bool(self.load)


@dataclass(frozen=True)
class Orchestration:
    schedule: str
    start_date: str = "2024-01-01"  # kept static so generated DAGs are deterministic
    dbt_command: str = "build"  # `build` also runs whatever tests the user adds


@dataclass(frozen=True)
class Targets:
    database: str = "duckdb"
    orchestrator: str = "airflow"
    #: Database file relative to the generated product directory. Every back-end
    #: points at this one location, so the artefacts compose into one pipeline.
    path: str = ""


@dataclass(frozen=True)
class Spec:
    product: str
    sources: tuple[Source, ...]
    layers: tuple[Layer, ...]
    orchestration: Orchestration
    targets: Targets

    @property
    def source_names(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.sources)

    @property
    def layer_names(self) -> tuple[str, ...]:
        return tuple(layer.name for layer in self.layers)

    def source(self, name: str) -> Source:
        for candidate in self.sources:
            if candidate.name == name:
                return candidate
        raise KeyError(name)

    def layer(self, name: str) -> Layer:
        for candidate in self.layers:
            if candidate.name == name:
                return candidate
        raise KeyError(name)

    def topological_layers(self) -> tuple[Layer, ...]:
        """Layers ordered so every layer follows the layers it depends on."""
        deps = {layer.name: layer.depends_on for layer in self.layers}
        order = topological_order(list(self.layer_names), deps)
        by_name = {layer.name: layer for layer in self.layers}
        return tuple(by_name[name] for name in order)
