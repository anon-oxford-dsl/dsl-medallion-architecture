# A Declarative Framework for Medallion Architecture Infrastructure Generation

`medallion` is a Python CLI that reads **one YAML specification** describing a medallion data
product and generates the infrastructure for it: DuckDB schema DDL, CSV ingestion, an Apache
Airflow orchestration DAG, and a dbt project skeleton.

It generates **scaffolding only**. It never generates transformation SQL: model directories
are created and left empty, because the business logic is yours to write. That boundary is
load-bearing, and it is verified by a test that asserts dbt's own manifest contains no models.

---

## Quick start

```sh
uv sync --all-groups                                     # full environment
uv run medallion validate  examples/customer_orders.yml
uv run medallion generate  examples/customer_orders.yml   # -> output/customer_orders/
uv run medallion metrics   examples/*.yml
```

`uv sync` alone installs a lighter environment: the CLI and everything except the Airflow and
dbt deployment tests, which then skip with an explanatory reason. Both are supported
configurations. Run `make help` for the full list of targets.

---

## The specification

```yaml
product: customer_orders

sources:
  orders:
    format: csv                       # csv only, by design
    path: data/raw/orders/*.csv       # glob, relative to this file
    columns:
      order_id: integer
      customer_id: integer
      amount: decimal

layers:
  bronze: { schema: raw,       load: [orders] }       # `load` makes a layer table-bearing
  silver: { schema: clean,     depends_on: [bronze] } # no `load` -> schema only
  gold:   { schema: analytics, depends_on: [silver] } # `schema` optional; defaults to the name

orchestration:
  schedule: "0 6 * * *"               # cron, passed to the DAG
  start_date: "2024-01-01"            # optional; default shown
  dbt_command: build                  # optional; `build` (default) or `run`

targets:
  database: duckdb
  orchestrator: airflow
  path: customer_orders.duckdb        # optional; the one database every artefact uses
```

A layer's **name is its identity** (it names the DAG task and the dbt model directory),
while `schema` is only its physical placement in the database. Two layers may not share a
schema; that is one of the semantic checks.

**Layer names are arbitrary.** `bronze`/`silver`/`gold` is a convention, not a rule: layers form
any acyclic `depends_on` graph, a layer with a non-empty `load` gets tables, and one without
gets a schema only. [`examples/retail_analytics.yml`](examples/retail_analytics.yml) uses a
five-layer fan-out/fan-in graph with different names.

**Column types** are abstract and map to DuckDB in one place
([`generators/types.py`](src/medallion/generators/types.py)):
`integer`, `bigint`, `decimal`, `double`, `float`, `string`, `boolean`, `date`, `timestamp`,
`time`.

---

## Architecture

A compiler-style front-end / back-end split, mirrored in the package layout.

```
YAML ──parse──▶ raw document ──JSON Schema──▶ validated ──lift──▶ Spec ──▶ four back-ends
                (line-tracked)   (structure)          (semantics)  (typed)
```

**Front-end** ([`src/medallion/frontend/`](src/medallion/frontend/)): the single source of
truth. `parse.py` loads YAML while recording source lines; `spec.schema.json` +
`schema.py` check structure with JSON Schema 2020-12; `lift.py` builds frozen dataclasses and
then enforces what JSON Schema cannot:

- every `depends_on` names a declared layer,
- every `load` entry names a declared source,
- at least one layer ingests something,
- the layer graph is acyclic.

All errors are collected, not fail-fast, and each is located:

```
$ medallion validate broken.yml
broken.yml:8: layers.bronze.load[0]: load references undeclared source 'order'
  hint: declared sources: orders
broken.yml:8: layers: dependency cycle: bronze -> gold -> silver -> bronze
  hint: layers must form an acyclic graph (bronze -> silver -> gold)
```

**Back-ends** ([`src/medallion/generators/`](src/medallion/generators/)): four independent
generators, each consuming only the typed model and rendering Jinja2 templates. A generator is
a pure function returning file contents; writing is a separate step, which is what makes the
golden-file and determinism tests possible.

| Generator | Output |
|---|---|
| `schema` | `schema/ddl.sql`: `CREATE SCHEMA` per layer in dependency order; `CREATE TABLE` only where `load` is declared |
| `ingestion` | `ingestion/load_bronze.py`: a runnable script loading each declared CSV into its layer, columns bound by name |
| `orchestration` | `orchestration/dags/<product>_dag.py`: `run_ingestion`, then one dbt task per layer, wired by `depends_on` |
| `scaffold` | `dbt/`: `dbt_project.yml`, `profiles.yml`, `models/sources.yml`, a schema-naming macro, and empty `models/<layer>/` |

Generated output is **deterministic**: no timestamps, tool versions, or absolute paths, so
generated infrastructure is reviewable in version control.

---

## Testing

Correctness is judged by the generated artefacts **running**, not by inspecting the generator.

```sh
make test-all      # everything, one environment      -> 167 passed
make test          # base environment only            -> 114 passed, 1 skipped
make test-int      # every deployment suite           ->  71 passed
```

| Layer | Count | What it covers |
|---|---|---|
| Front-end unit | 41 | valid specs lift correctly; each semantic rule rejects the right malformed spec with a located, helpful message |
| Generation | 38 | golden/snapshot comparison (`UPDATE_GOLDEN=1` to refresh), byte-level determinism, target dispatch, and generalisation beyond bronze/silver/gold |
| Metrics | 17 | pins the *definitions* of every reported figure |
| **DuckDB deployment** | 18 | the DDL executes on a real engine and the ingestion script runs as a subprocess; schema mapping, column types and order, row counts, idempotency |
| **Airflow deployment** | 31 | the DAG imports with no errors, passes `DAG.validate()`, and its tasks (including `run_ingestion`) are wired exactly as declared |
| **dbt deployment** | 20 | `dbt parse` and `dbt compile` exit 0; the manifest matches the spec, and contains **no models** |
| **End-to-end** | 2 | DDL → ingestion script → `dbt build` against one database, with a user-written model reading through `source()` |

Deployment tests run against **all three example scenarios**, and skip with an explanatory
reason (never fail) if their toolchain is absent.

---

## Metrics

`medallion metrics` reports specification size against generated output, and the complexity of
the generated DAG. Artefacts are measured in memory, so a report can never describe a stale
build directory.

```
$ make metrics
scenario          spec LOC  gen LOC  ratio  files  tasks  edges  depth  density  cyclo
----------------  --------  -------  -----  -----  -----  -----  -----  -------  -----
minimal           16        134      8.38x  8      2      1      2      1.00     1
customer_orders   24        155      6.46x  10     4      3      4      0.50     1
retail_analytics  44        227      5.16x  12     6      7      4      0.47     3
```

`--json` emits the same figures machine-readably, with the blank/comment/code breakdown per
back-end. Lines are counted identically on both sides of the comparison (Python docstrings are
located with `ast` and counted as comments), so the ratio compares like with like. Note that
the ratio *falls* as specifications grow: generated output carries a fixed overhead (the
ingestion script, profile, project config and DAG preamble) that amortises. `tasks` counts the
tasks the DAG actually contains, which is one per layer plus `run_ingestion`.

---

## Reproducibility

`uv.lock` is the source of truth: Python 3.12, `apache-airflow==3.3.1`, `dbt-core==1.12.3`,
`dbt-duckdb==1.11.0`, `duckdb==1.5.5`, `jinja2==3.1.6`, `jsonschema==4.26.0`, `pyyaml==6.0.3`,
`pytest==8.4.2`, `ruff==0.16.5`. Human-readable exports live in
[`requirements/`](requirements/).
