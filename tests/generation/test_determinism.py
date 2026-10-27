"""Determinism: the same specification must always produce byte-identical output.

This is what makes golden comparison meaningful and makes generated
infrastructure reviewable in version control.
"""

from __future__ import annotations

import re
from pathlib import Path

from medallion.frontend.lift import lift
from medallion.frontend.parse import parse_spec_file
from medallion.generators import generate_all, write_files


def test_repeated_generation_is_byte_identical(render_all, example_spec):
    assert render_all(example_spec) == render_all(example_spec)


def test_generation_is_stable_across_reloads_of_the_spec(render_all, example_spec_path):
    first = render_all(lift(parse_spec_file(example_spec_path), source=str(example_spec_path)))
    second = render_all(lift(parse_spec_file(example_spec_path), source=str(example_spec_path)))
    assert first == second


def test_written_files_are_byte_identical(example_spec, tmp_path):
    def write(target: Path) -> dict[str, bytes]:
        for files in generate_all(example_spec).values():
            write_files(files, target)
        return {
            str(p.relative_to(target)): p.read_bytes()
            for p in sorted(target.rglob("*"))
            if p.is_file()
        }

    assert write(tmp_path / "a") == write(tmp_path / "b")


def test_output_contains_no_timestamps_or_absolute_paths(render_all, example_spec):
    """Provenance headers must not embed anything machine- or time-dependent."""
    forbidden = re.compile(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"  # ISO timestamp
        r"|/Users/|/home/|C:\\\\"  # absolute paths
        r"|generated at",
        re.IGNORECASE,
    )
    for path, content in render_all(example_spec).items():
        match = forbidden.search(content)
        assert match is None, f"{path} contains non-deterministic content: {match!r}"
