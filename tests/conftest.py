from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from medallion.frontend.lift import lift
from medallion.frontend.model import Spec
from medallion.frontend.parse import parse_spec_file, parse_text
from medallion.generators import generate_all

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def examples_dir() -> Path:
    return EXAMPLES_DIR


@pytest.fixture
def example_spec_path() -> Path:
    return EXAMPLES_DIR / "customer_orders.yml"


@pytest.fixture
def example_spec(example_spec_path: Path) -> Spec:
    return lift(parse_spec_file(example_spec_path), source=str(example_spec_path))


@pytest.fixture
def lift_yaml():
    """Lift an inline YAML string, dedented for readability in tests."""

    def _lift(text: str) -> Spec:
        return lift(parse_text(textwrap.dedent(text)), source="<inline>")

    return _lift


@pytest.fixture
def render_all():
    """Render every artefact for a spec, keyed by relative path.

    Generators are pure, so this needs no filesystem -- which is what lets the
    golden and determinism tests compare content directly.
    """

    def _render(spec: Spec) -> dict[str, str]:
        return {
            str(generated.path): generated.content
            for files in generate_all(spec).values()
            for generated in files
        }

    return _render
