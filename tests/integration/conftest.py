"""Fixtures for the deployment tests.

Correctness here is judged by generated artefacts *running* against the real
tools, not by inspecting the generator.

Airflow reads configuration at import time, so its environment is set up here --
this conftest is imported before any test module in this directory.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from medallion.frontend.lift import lift
from medallion.frontend.parse import parse_spec_file
from medallion.generators import generate_all, write_files

# Point Airflow at a scratch home and suppress its bundled example DAGs before
# `import airflow` happens anywhere. In Airflow 3 the DagBag `include_examples`
# argument no longer exists, so this is the supported way to exclude them.
os.environ.setdefault("AIRFLOW_HOME", tempfile.mkdtemp(prefix="medallion-airflow-"))
os.environ.setdefault("AIRFLOW__CORE__LOAD_EXAMPLES", "False")
os.environ.setdefault("AIRFLOW__CORE__UNIT_TEST_MODE", "True")

#: Every shipped scenario is deployed, not just the illustrative one.
SCENARIOS = ["minimal", "customer_orders", "retail_analytics"]


def pytest_generate_tests(metafunc):
    """Any deployment test taking a ``scenario`` argument runs for every scenario."""
    if "scenario" in metafunc.fixturenames:
        metafunc.parametrize("scenario", SCENARIOS)


@pytest.fixture(scope="session")
def _generated_root(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("generated")


@pytest.fixture(scope="session")
def deployment(_generated_root):
    """Generate a named scenario once per session and return (spec, output dir).

    Used via ``request.getfixturevalue`` so tests can parametrise over scenarios.
    """
    examples = Path(__file__).resolve().parents[2] / "examples"
    cache: dict[str, tuple] = {}

    def _deploy(scenario: str):
        if scenario not in cache:
            spec_path = examples / f"{scenario}.yml"
            spec = lift(parse_spec_file(spec_path), source=str(spec_path))
            out_dir = _generated_root / scenario
            for files in generate_all(spec).values():
                write_files(files, out_dir)
            cache[scenario] = (spec, out_dir)
        return cache[scenario]

    return _deploy


@pytest.fixture(scope="session")
def examples_root() -> Path:
    return Path(__file__).resolve().parents[2] / "examples"
