"""YAML loading with source-line tracking.

``safe_load`` throws away line numbers. We use a ``SafeLoader`` subclass that
returns a ``dict`` subclass (:class:`LinedMap`) carrying the line where each
mapping began, so downstream validation can point the author at the right place.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .errors import SpecError, SpecValidationError


class LinedMap(dict):
    """A plain mapping (for JSON Schema purposes) that also records its source line."""

    line: int = 0


class _LineLoader(yaml.SafeLoader):
    pass


def _construct_lined_map(loader: _LineLoader, node: yaml.MappingNode) -> LinedMap:
    mapping = LinedMap()
    mapping.line = node.start_mark.line + 1
    mapping.update(loader.construct_mapping(node, deep=True))
    return mapping


_LineLoader.add_constructor("tag:yaml.org,2002:map", _construct_lined_map)


def parse_text(text: str, source: str = "<spec>") -> LinedMap:
    """Parse YAML text into a :class:`LinedMap`, or raise :class:`SpecValidationError`."""
    try:
        # _LineLoader subclasses SafeLoader, so this is a safe load.
        data = yaml.load(text, Loader=_LineLoader)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark
        message = (exc.problem or "invalid YAML").strip()
        raise SpecValidationError(
            [SpecError(path="", message=message, line=(mark.line + 1) if mark else None)],
            source=source,
        ) from exc
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise SpecValidationError(
            [SpecError(path="", message=f"invalid YAML: {exc}")], source=source
        ) from exc

    if data is None:
        raise SpecValidationError(
            [SpecError(path="", message="specification is empty")], source=source
        )
    if not isinstance(data, dict):
        raise SpecValidationError(
            [SpecError(path="", message="specification must be a YAML mapping at the top level")],
            source=source,
        )
    return data if isinstance(data, LinedMap) else LinedMap(data)


def parse_spec_file(path: str | Path) -> LinedMap:
    """Read and parse a spec file. Raises :class:`SpecValidationError` on any failure."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SpecValidationError(
            [SpecError(path="", message="no such file")], source=str(path)
        ) from exc
    return parse_text(text, source=str(path))
