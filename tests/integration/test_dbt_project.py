"""Deployment test: the generated dbt project must parse and compile.

Run with the dbt environment: ``uv run --group dbt pytest -m dbt``.

dbt is driven through its CLI in a subprocess rather than its Python API: that is
how a user actually runs the generated project, and it keeps the test independent
of dbt's internal interfaces.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
import yaml

from medallion.generators.types import dbt_data_type

DBT = shutil.which("dbt")

pytestmark = [
    pytest.mark.dbt,
    pytest.mark.skipif(
        DBT is None,
        reason="dbt is not installed; run with `uv run --group dbt pytest -m dbt`",
    ),
]


def _run_dbt(command: str, project_dir):
    return subprocess.run(
        [
            DBT,
            command,
            "--project-dir",
            str(project_dir),
            "--profiles-dir",
            str(project_dir),
        ],
        capture_output=True,
        text=True,
        cwd=str(project_dir),
        check=False,
    )


@pytest.fixture(scope="session")
def parsed(deployment):
    """Run `dbt parse` once per scenario; return (spec, project dir, result, manifest)."""
    cache: dict[str, tuple] = {}

    def _parse(scenario: str):
        if scenario not in cache:
            spec, out_dir = deployment(scenario)
            project_dir = out_dir / "dbt"
            result = _run_dbt("parse", project_dir)
            manifest_path = project_dir / "target" / "manifest.json"
            manifest = (
                json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest_path.exists()
                else None
            )
            cache[scenario] = (spec, project_dir, result, manifest)
        return cache[scenario]

    return _parse


def test_dbt_parse_succeeds(parsed, scenario):
    _, _, result, _ = parsed(scenario)
    assert result.returncode == 0, f"dbt parse failed:\n{result.stdout}\n{result.stderr}"


def test_dbt_parse_writes_a_manifest(parsed, scenario):
    _, project_dir, _, manifest = parsed(scenario)
    assert (project_dir / "target" / "manifest.json").exists()
    assert manifest is not None


def test_manifest_declares_every_source_table(parsed, scenario):
    spec, _, _, manifest = parsed(scenario)

    declared = {
        (node["source_name"], node["name"], node["schema"]) for node in manifest["sources"].values()
    }
    # The dbt source is named for the layer but resolves to its mapped schema,
    # the same schema the generated DDL creates.
    expected = {
        (layer.name, source_name, layer.schema)
        for layer in spec.layers
        for source_name in layer.load
    }
    assert declared == expected


def test_manifest_carries_the_declared_columns(parsed, scenario):
    spec, _, _, manifest = parsed(scenario)
    by_table = {(n["source_name"], n["name"]): n for n in manifest["sources"].values()}

    for layer in spec.layers:
        for source_name in layer.load:
            columns = by_table[(layer.name, source_name)]["columns"]
            source = spec.source(source_name)
            assert list(columns) == [c.name for c in source.columns]
            for column in source.columns:
                assert columns[column.name]["data_type"] == dbt_data_type(column.type)


def test_no_models_are_generated(parsed, scenario):
    """The load-bearing boundary: scaffolding only, never transformation SQL."""
    _, _, _, manifest = parsed(scenario)
    assert manifest["nodes"] == {}, "the generator must not produce dbt models"


def test_model_directories_exist_and_are_empty(parsed, scenario):
    spec, project_dir, _, _ = parsed(scenario)
    for layer in spec.layers:
        directory = project_dir / "models" / layer.name
        assert directory.is_dir()
        assert [p.name for p in directory.iterdir()] == [".gitkeep"]


def test_dbt_compile_succeeds(deployment):
    _, out_dir = deployment("customer_orders")
    result = _run_dbt("compile", out_dir / "dbt")
    assert result.returncode == 0, f"dbt compile failed:\n{result.stdout}\n{result.stderr}"


def test_generated_profile_targets_duckdb(deployment):
    _, out_dir = deployment("customer_orders")
    profile = yaml.safe_load((out_dir / "dbt" / "profiles.yml").read_text(encoding="utf-8"))
    assert profile["customer_orders"]["outputs"]["dev"]["type"] == "duckdb"
