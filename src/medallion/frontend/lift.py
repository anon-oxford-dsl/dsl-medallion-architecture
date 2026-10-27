"""Lift a parsed document into the typed :class:`Spec`.

Pipeline: structural validation (JSON Schema) -> build dataclasses -> semantic
checks that JSON Schema cannot express (dependency references resolve, load
references resolve, the layer graph is acyclic, something is actually ingested).
Every failure is raised as a :class:`SpecValidationError` carrying located
:class:`SpecError` diagnostics.
"""

from __future__ import annotations

from .errors import SpecError, SpecValidationError
from .graph import detect_cycle
from .model import (
    AbstractType,
    Column,
    Layer,
    Orchestration,
    Source,
    Spec,
    Targets,
)
from .schema import validate_structure


def lift(doc: object, source: str = "<spec>") -> Spec:
    structural = validate_structure(doc)
    if structural:
        raise SpecValidationError(structural, source)

    spec = _build(doc)

    semantic = _semantic_errors(spec, doc)
    if semantic:
        raise SpecValidationError(semantic, source)
    return spec


def _build(doc: dict) -> Spec:
    sources = tuple(
        Source(
            name=name,
            format=body["format"],
            path=body["path"],
            columns=tuple(
                Column(name=col, type=AbstractType(col_type))
                for col, col_type in body["columns"].items()
            ),
        )
        for name, body in doc["sources"].items()
    )
    # Optional fields are defaulted here, once, so the typed model always carries
    # concrete values and no back-end re-implements a default.
    layers = tuple(
        Layer(
            name=name,
            schema=(body or {}).get("schema", name),
            load=tuple((body or {}).get("load", ())),
            depends_on=tuple((body or {}).get("depends_on", ())),
        )
        for name, body in doc["layers"].items()
    )
    orch_doc = doc["orchestration"]
    orchestration = Orchestration(
        schedule=orch_doc["schedule"],
        start_date=orch_doc.get("start_date", Orchestration.start_date),
        dbt_command=orch_doc.get("dbt_command", Orchestration.dbt_command),
    )
    targets_doc = doc["targets"]
    targets = Targets(
        database=targets_doc["database"],
        orchestrator=targets_doc["orchestrator"],
        path=targets_doc.get("path", f"{doc['product']}.duckdb"),
    )
    return Spec(
        product=doc["product"],
        sources=sources,
        layers=layers,
        orchestration=orchestration,
        targets=targets,
    )


def _layer_line(doc: dict, layer: str) -> int | None:
    node = doc.get("layers", {}).get(layer)
    return getattr(node, "line", None) or getattr(doc.get("layers"), "line", None)


def _semantic_errors(spec: Spec, doc: dict) -> list[SpecError]:
    errors: list[SpecError] = []
    known_layers = set(spec.layer_names)
    known_sources = set(spec.source_names)

    for layer in spec.layers:
        line = _layer_line(doc, layer.name)
        for index, dep in enumerate(layer.depends_on):
            if dep not in known_layers:
                errors.append(
                    SpecError(
                        path=f"layers.{layer.name}.depends_on[{index}]",
                        message=f"depends_on references unknown layer '{dep}'",
                        hint=f"declared layers: {', '.join(spec.layer_names)}",
                        line=line,
                    )
                )
        for index, src in enumerate(layer.load):
            if src not in known_sources:
                errors.append(
                    SpecError(
                        path=f"layers.{layer.name}.load[{index}]",
                        message=f"load references undeclared source '{src}'",
                        hint=f"declared sources: {', '.join(spec.source_names)}",
                        line=line,
                    )
                )

    # Two layers sharing a schema would silently collide in the database: their
    # tables would land together and dbt would materialise into the same place.
    seen_schemas: dict[str, str] = {}
    for layer in spec.layers:
        owner = seen_schemas.get(layer.schema)
        if owner is not None:
            errors.append(
                SpecError(
                    path=f"layers.{layer.name}.schema",
                    message=(
                        f"schema '{layer.schema}' is already used by layer '{owner}'; "
                        "two layers cannot share a schema"
                    ),
                    hint="give each layer its own `schema`, or omit it to use the layer name",
                    line=_layer_line(doc, layer.name),
                )
            )
        else:
            seen_schemas[layer.schema] = layer.name

    if not any(layer.load for layer in spec.layers):
        errors.append(
            SpecError(
                path="layers",
                message="no layer declares a `load`; nothing would be ingested",
                hint="give your base layer `load: [<source>, ...]`",
                line=getattr(doc.get("layers"), "line", None),
            )
        )

    deps = {layer.name: layer.depends_on for layer in spec.layers}
    cycle = detect_cycle(list(spec.layer_names), deps)
    if cycle is not None:
        errors.append(
            SpecError(
                path="layers",
                message="dependency cycle: " + " -> ".join(cycle),
                hint="layers must form an acyclic graph (bronze -> silver -> gold)",
                line=getattr(doc.get("layers"), "line", None),
            )
        )

    return errors
