"""Golden-file (snapshot) tests.

Every generator is rendered for the illustrative specification and compared
byte-for-byte against a committed expected artefact. Regenerate deliberately with:

    UPDATE_GOLDEN=1 uv run pytest tests/generation

A diff here means generated output changed: review it, then update the goldens.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path

import pytest

from medallion.generators import GENERATORS, generate_all

GOLDEN_DIR = Path(__file__).parent / "golden"
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"


def test_generated_file_set_matches_golden(render_all, example_spec):
    produced = set(render_all(example_spec))
    if UPDATE:
        pytest.skip("UPDATE_GOLDEN=1: writing goldens, not comparing")
    expected = {
        str(path.relative_to(GOLDEN_DIR)) for path in GOLDEN_DIR.rglob("*") if path.is_file()
    }
    assert produced == expected


@pytest.mark.parametrize(
    "relative_path",
    [
        "schema/ddl.sql",
        "ingestion/load_bronze.py",
        "orchestration/dags/customer_orders_dag.py",
        "dbt/dbt_project.yml",
        "dbt/profiles.yml",
        "dbt/models/sources.yml",
        "dbt/macros/generate_schema_name.sql",
        "dbt/models/bronze/.gitkeep",
        "dbt/models/silver/.gitkeep",
        "dbt/models/gold/.gitkeep",
    ],
)
def test_artefact_matches_golden(render_all, example_spec, relative_path):
    actual = render_all(example_spec)[relative_path]
    golden = GOLDEN_DIR / relative_path

    if UPDATE:
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual, encoding="utf-8")
        pytest.skip(f"UPDATE_GOLDEN=1: wrote {relative_path}")

    assert golden.exists(), f"missing golden for {relative_path}"
    expected = golden.read_text(encoding="utf-8")
    if actual != expected:
        diff = "\n".join(
            difflib.unified_diff(
                expected.splitlines(),
                actual.splitlines(),
                fromfile=f"golden/{relative_path}",
                tofile=f"generated/{relative_path}",
                lineterm="",
            )
        )
        pytest.fail(f"generated output drifted from golden:\n{diff}")


def test_every_generator_is_covered(example_spec):
    """Guard against a new generator silently escaping golden coverage."""
    produced = generate_all(example_spec)
    assert set(produced) == set(GENERATORS)
    for name, files in produced.items():
        assert files, f"generator '{name}' produced no files"
