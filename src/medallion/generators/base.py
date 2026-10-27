"""Back-end plumbing shared by every generator.

A generator is a pure function of the typed :class:`~medallion.frontend.model.Spec`:
it returns :class:`GeneratedFile` values with *relative* paths and never touches the
filesystem. Writing is a separate step (:func:`write_files`), which keeps the
golden-file tests filesystem-free and makes determinism easy to assert.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath

from jinja2 import Environment, PackageLoader, StrictUndefined

from ..frontend.model import Spec


@dataclass(frozen=True)
class GeneratedFile:
    """One artefact: a path relative to the output directory, plus its full content."""

    path: PurePosixPath
    content: str


@lru_cache(maxsize=1)
def template_env() -> Environment:
    """Shared Jinja environment.

    ``StrictUndefined`` turns a typo in a template into a loud error rather than a
    silently empty artefact; ``keep_trailing_newline`` keeps rendered files
    POSIX-clean and byte-comparable against golden files.
    """
    return Environment(
        loader=PackageLoader("medallion.generators", "templates"),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
        # We generate SQL, Python and YAML, never HTML, so escaping would corrupt output.
        autoescape=False,
    )


class Generator(ABC):
    """One back-end target. Consumes only the typed model."""

    #: Stable identifier, used by ``--only`` and by the metrics harness.
    name: str
    #: One-line description shown in ``medallion generate --help``.
    description: str
    #: The declared targets this generator serves, e.g. ``{"database": "duckdb"}``.
    #: The engine checks these against ``spec.targets`` before running it, so adding
    #: a second database means adding a generator, not editing the engine.
    supports: dict[str, str] = {}  # noqa: RUF012 - a class-level declaration, never mutated

    @abstractmethod
    def generate(self, spec: Spec) -> list[GeneratedFile]:
        """Render this target's artefacts for ``spec``."""

    def render(self, template: str, /, **context: object) -> str:
        return template_env().get_template(template).render(**context)


class UnsupportedTargetError(Exception):
    """Raised when a generator cannot serve the targets a specification declares."""


def write_files(files: list[GeneratedFile], out_dir: Path) -> list[Path]:
    """Write generated files under ``out_dir``, creating parent directories."""
    written: list[Path] = []
    for generated in files:
        target = out_dir / Path(str(generated.path))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(generated.content, encoding="utf-8")
        written.append(target)
    return written
