"""The abstract type vocabulary. Concrete DuckDB/dbt mappings are tested in Block 2."""

from __future__ import annotations

import pytest

from medallion.frontend.model import AbstractType

EXPECTED_VOCABULARY = {
    "integer",
    "bigint",
    "decimal",
    "double",
    "float",
    "string",
    "boolean",
    "date",
    "timestamp",
    "time",
}


def test_vocabulary_is_exactly_as_documented():
    assert {t.value for t in AbstractType} == EXPECTED_VOCABULARY


def test_lookup_by_value():
    assert AbstractType("decimal") is AbstractType.DECIMAL


def test_unknown_type_raises():
    with pytest.raises(ValueError):
        AbstractType("money")
