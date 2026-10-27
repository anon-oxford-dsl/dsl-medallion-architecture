"""Concrete type mappings: the only place abstract types meet a real database.

The front-end owns the abstract vocabulary (``AbstractType`` in
``frontend/model.py``); this module is a back-end concern and maps it to DuckDB.
"""

from __future__ import annotations

from ..frontend.model import AbstractType

#: Abstract type -> DuckDB column type.
DUCKDB_TYPES: dict[AbstractType, str] = {
    AbstractType.INTEGER: "INTEGER",
    AbstractType.BIGINT: "BIGINT",
    AbstractType.DECIMAL: "DECIMAL(18,2)",
    AbstractType.DOUBLE: "DOUBLE",
    AbstractType.FLOAT: "FLOAT",
    AbstractType.STRING: "VARCHAR",
    AbstractType.BOOLEAN: "BOOLEAN",
    AbstractType.DATE: "DATE",
    AbstractType.TIMESTAMP: "TIMESTAMP",
    AbstractType.TIME: "TIME",
}


def duckdb_type(abstract: AbstractType) -> str:
    """DuckDB column type for an abstract type."""
    return DUCKDB_TYPES[abstract]


def dbt_data_type(abstract: AbstractType) -> str:
    """``data_type`` for a dbt ``sources.yml`` column.

    Deliberately the same string as :func:`duckdb_type`: the target warehouse is
    DuckDB, so the documented type *is* the DuckDB type. A second mapping table
    would be a second source of truth, free to drift from the DDL we emit.
    """
    return DUCKDB_TYPES[abstract]
