"""Structural / syntactic validation against ``spec.schema.json`` (JSON Schema 2020-12)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources

from jsonschema import Draft202012Validator

from .errors import SpecError

_ALLOWED_TYPES = "integer, bigint, decimal, double, float, string, boolean, date, timestamp, time"


@lru_cache(maxsize=1)
def load_schema() -> dict:
    text = (resources.files("medallion.frontend") / "spec.schema.json").read_text("utf-8")
    schema = json.loads(text)
    Draft202012Validator.check_schema(schema)
    return schema


def _path_str(parts: list[object]) -> str:
    out = ""
    for part in parts:
        if isinstance(part, int):
            out += f"[{part}]"
        elif out:
            out += f".{part}"
        else:
            out = str(part)
    return out


def _line_for(doc: object, parts: list[object]) -> int | None:
    node = doc
    line = getattr(doc, "line", None)
    for part in parts:
        in_dict = isinstance(node, dict) and part in node
        in_list = isinstance(node, list) and isinstance(part, int) and 0 <= part < len(node)
        if not (in_dict or in_list):
            break
        node = node[part]
        if getattr(node, "line", None):
            line = node.line
    return line


def _hint_for(error) -> str | None:
    if error.validator == "enum":
        choices = error.validator_value
        if choices == ["csv"]:
            return "only 'csv' sources are supported in this version"
        if set(choices) <= {"duckdb", "airflow"}:
            return f"supported values: {', '.join(choices)}"
        if "integer" in choices:
            return f"allowed column types: {_ALLOWED_TYPES}"
    if error.validator == "pattern":
        if error.absolute_path and error.absolute_path[-1] == "product":
            return "product must be a lowercase identifier, e.g. customer_orders"
        return "use lowercase letters, digits and underscores; must start with a letter"
    if error.validator == "additionalProperties":
        return "remove the unexpected key or check it for a typo"
    return None


def validate_structure(doc: object) -> list[SpecError]:
    """Return every structural error in ``doc``, ordered by position in the document."""
    validator = Draft202012Validator(load_schema())
    raw = sorted(
        validator.iter_errors(doc),
        key=lambda e: (list(e.absolute_path), e.validator),
    )

    errors: list[SpecError] = []
    for error in raw:
        parts = list(error.absolute_path)
        message = error.message
        # jsonschema reports `required` at the parent; surface the missing key in the path.
        if error.validator == "required":
            match = re.search(r"'([^']+)' is a required property", error.message)
            if match:
                parts = [*parts, match.group(1)]
                message = "missing required key"
        errors.append(
            SpecError(
                path=_path_str(parts),
                message=message,
                hint=_hint_for(error),
                line=_line_for(doc, list(error.absolute_path)),
            )
        )
    return errors
