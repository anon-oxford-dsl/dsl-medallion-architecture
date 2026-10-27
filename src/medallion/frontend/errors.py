"""Located, user-facing specification errors.

`SpecError` is a single diagnostic (never raised on its own); `SpecValidationError`
is the exception that carries one or more of them out of the front-end.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpecError:
    """One diagnostic about a specification.

    Attributes:
        path: dotted / indexed pointer into the document
            (e.g. ``layers.silver.depends_on[0]``); empty for whole-document errors.
        message: what is wrong, phrased for the spec author.
        hint: optional suggested fix.
        line: 1-based source line, when the offending node could be located.
    """

    path: str
    message: str
    hint: str | None = None
    line: int | None = None

    def format(self, source: str) -> str:
        where = source
        if self.line is not None:
            where = f"{where}:{self.line}"
        if self.path:
            where = f"{where}: {self.path}"
        text = f"{where}: {self.message}"
        if self.hint:
            text = f"{text}\n  hint: {self.hint}"
        return text


class SpecValidationError(Exception):
    """Raised by the front-end when a spec cannot be parsed, validated or lifted."""

    def __init__(self, errors: list[SpecError], source: str = "<spec>") -> None:
        self.errors = list(errors)
        self.source = source
        super().__init__(f"{len(self.errors)} error(s) in {source}")

    def format(self) -> str:
        return "\n".join(error.format(self.source) for error in self.errors)
