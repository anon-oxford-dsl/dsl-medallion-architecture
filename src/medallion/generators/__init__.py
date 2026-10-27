"""Back-ends. Each generator consumes only the typed model and is independent."""

from __future__ import annotations

from ..frontend.model import Spec
from .base import GeneratedFile, Generator, UnsupportedTargetError, write_files
from .ingestion import IngestionGenerator
from .orchestration import OrchestrationGenerator
from .scaffold import ScaffoldGenerator
from .schema_ddl import SchemaGenerator

#: Registry in the order artefacts are generated and reported.
GENERATORS: dict[str, type[Generator]] = {
    generator.name: generator
    for generator in (
        SchemaGenerator,
        IngestionGenerator,
        OrchestrationGenerator,
        ScaffoldGenerator,
    )
}

__all__ = [
    "GENERATORS",
    "GeneratedFile",
    "Generator",
    "IngestionGenerator",
    "OrchestrationGenerator",
    "ScaffoldGenerator",
    "SchemaGenerator",
    "UnsupportedTargetError",
    "check_targets",
    "generate_all",
    "write_files",
]


def check_targets(generator: type[Generator], spec: Spec) -> None:
    """Verify a generator serves the targets ``spec`` declares.

    Raises:
        UnsupportedTargetError: naming the generator, the target and both values.
    """
    for target, required in generator.supports.items():
        declared = getattr(spec.targets, target)
        if declared != required:
            raise UnsupportedTargetError(
                f"generator '{generator.name}' supports {target} '{required}', "
                f"but the specification declares '{declared}'"
            )


def generate_all(spec: Spec, only: list[str] | None = None) -> dict[str, list[GeneratedFile]]:
    """Run every generator (or just ``only``), keyed by generator name.

    Each generator is dispatched on the targets the specification declares, so an
    unsupported combination fails loudly instead of silently emitting the wrong
    artefacts.
    """
    names = list(GENERATORS) if only is None else list(only)
    artefacts: dict[str, list[GeneratedFile]] = {}
    for name in names:
        generator = GENERATORS[name]
        check_targets(generator, spec)
        artefacts[name] = generator().generate(spec)
    return artefacts
