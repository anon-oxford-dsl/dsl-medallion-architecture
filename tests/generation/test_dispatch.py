"""The generator engine dispatches on the targets a specification declares.

The JSON Schema admits exactly one value per target today, so an unsupported
combination cannot be written in YAML. These tests construct a ``Spec`` directly
to exercise the engine, which is what makes the extension point real rather than
decorative: adding a second database means adding a generator that declares it.
"""

from __future__ import annotations

import dataclasses

import pytest

from medallion.generators import (
    GENERATORS,
    UnsupportedTargetError,
    check_targets,
    generate_all,
)


def test_every_generator_declares_the_targets_it_serves():
    declared = {name: cls.supports for name, cls in GENERATORS.items()}
    assert declared == {
        "schema": {"database": "duckdb"},
        "ingestion": {"database": "duckdb"},
        "orchestration": {"orchestrator": "airflow"},
        "scaffold": {"database": "duckdb"},
    }


def test_declared_targets_name_real_fields_on_the_model(example_spec):
    for cls in GENERATORS.values():
        for target in cls.supports:
            assert hasattr(example_spec.targets, target), target


def test_supported_targets_pass(example_spec):
    for cls in GENERATORS.values():
        check_targets(cls, example_spec)


def _with_targets(spec, **changes):
    targets = dataclasses.replace(spec.targets, **changes)
    return dataclasses.replace(spec, targets=targets)


def test_unsupported_database_is_refused(example_spec):
    spec = _with_targets(example_spec, database="postgres")
    with pytest.raises(UnsupportedTargetError) as excinfo:
        generate_all(spec)
    message = str(excinfo.value)
    assert "schema" in message
    assert "duckdb" in message and "postgres" in message


def test_unsupported_orchestrator_is_refused(example_spec):
    spec = _with_targets(example_spec, orchestrator="dagster")
    with pytest.raises(UnsupportedTargetError) as excinfo:
        generate_all(spec, only=["orchestration"])
    assert "orchestration" in str(excinfo.value)
    assert "dagster" in str(excinfo.value)


def test_a_generator_unaffected_by_the_change_still_runs(example_spec):
    """An unsupported orchestrator must not block the database back-ends."""
    spec = _with_targets(example_spec, orchestrator="dagster")
    artefacts = generate_all(spec, only=["schema", "ingestion", "scaffold"])
    assert set(artefacts) == {"schema", "ingestion", "scaffold"}
