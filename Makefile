# Thin wrappers over uv.
.PHONY: help sync sync-all lint fmt check test test-duckdb test-airflow test-dbt test-int \
        test-all example metrics metrics-json requirements clean

help:              ## list the available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

sync:              ## base environment: the CLI plus front-end/generation/metrics tests
	uv sync

sync-all:          ## full environment: adds Airflow and dbt for the deployment tests
	uv sync --all-groups

lint:              ## static checks
	uv run ruff check src tests

fmt:               ## apply formatting
	uv run ruff format src tests

check: lint        ## lint plus a formatting check
	uv run ruff format --check src tests

test:              ## front-end, generation, metrics and DuckDB deployment (base env)
	uv run pytest -m "not airflow and not dbt"

test-duckdb:       ## DuckDB deployment tests only
	uv run pytest -m duckdb

test-airflow:      ## Airflow DAG-validation tests only
	uv run --group airflow pytest -m airflow

test-dbt:          ## dbt parse/compile tests only
	uv run --group dbt pytest -m dbt

test-int:          ## all three deployment suites, in one environment
	uv run --all-groups pytest -m "duckdb or airflow or dbt"

test-all:          ## the complete suite in one environment
	uv run --all-groups pytest

example:           ## generate artefacts for the illustrative specification
	uv run medallion generate examples/customer_orders.yml

metrics:           ## evaluation table across every example scenario
	uv run medallion metrics examples/minimal.yml examples/customer_orders.yml \
	  examples/retail_analytics.yml

metrics-json:      ## the same figures as JSON
	uv run medallion metrics examples/minimal.yml examples/customer_orders.yml \
	  examples/retail_analytics.yml --json

requirements:      ## regenerate the pinned requirements appendix from uv.lock
	uv export --format requirements-txt --no-hashes --no-emit-project -o requirements/base.txt -q
	uv export --format requirements-txt --no-hashes --no-emit-project --group airflow \
	  -o requirements/airflow.txt -q
	uv export --format requirements-txt --no-hashes --no-emit-project --group dbt \
	  -o requirements/dbt.txt -q
	uv export --format requirements-txt --no-hashes --no-emit-project --all-groups \
	  -o requirements/all.txt -q

clean:             ## remove generated and cache directories
	rm -rf output build .pytest_cache .ruff_cache
