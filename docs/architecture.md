# Architecture and execution boundaries

## Scope

A small, complete reference implementation of semantic query planning. The supported
Ossie subset is explicit; this is not a complete implementation of the Ossie specification
or a production governance platform. SemanticOps is a separate future project.

## Query pipeline

1. `parsing.py` interprets a question into `SemanticQuery`; structured callers skip it.
2. `catalog.py` validates model definitions and metric expressions.
3. `planning/resolver.py` resolves dimensions, safe join paths, and one branch per fact.
4. `planning/compiler.py` compiles branches and merges aggregated group keys.
5. `database.py` executes the compiled SQL and parameters through a read-only connection.
6. `service.py` returns the semantic query, logical plan, SQL, explanation, and results.

`SemanticService.plan()` is the common planning entry point for CLI, HTTP, and execution.
It does not open, initialize, or query a database. `query()` extends that exact trace with
execution results. No agent framework is required to call either method.

## Initialization is an application decision

`Database.run()`, `overview()`, and `preview()` never seed a warehouse. Missing files fail
without creating a directory or database. `demo_data.seed_demo()` owns fixture loading and
transactional reset; `Database.seed()` remains a compatibility entry point. A failed reset
rolls back the existing tables and rows.

The default local application and CLI retain first-use demo bootstrap for ease of use.
An injected database disables bootstrap by default:

```python
from ossie_demo.database import Database
from ossie_demo.service import SemanticService

service = SemanticService(database=Database("warehouse.duckdb"))
# To explicitly opt into demo initialization:
demo = SemanticService(database=Database("demo.duckdb"), bootstrap_demo=True)
```

Existing files are never automatically reset. Explicit reset is a local demo operation.
The table explorer remains specific to the four example tables; it is not a general
warehouse catalog. Concurrent first-use initialization is not a production migration system.

## Aggregation semantics

- Aggregate each fact independently before combining results.
- Reconcile the union of group keys, including a NULL key from an unmatched dimension.
- A group absent from one fact retains NULL for that fact's metrics; do not silently
  convert absence into zero.
- For an empty ungrouped input, COUNT is zero and SUM and a zero-denominator ratio are NULL.
- Empty grouped input returns no groups.
- Recompute ratios and distinct counts at the requested grain; do not sum displayed ratios.

Tests assert these results on both DuckDB and SQLite. NULL sort position is engine-specific;
key alignment and metric values must agree.

## Error contract

HTTP errors contain a string `detail` for existing clients and an `error` object with
`code`, `stage`, and `message`.

| Code | Stage | HTTP status |
| --- | --- | --- |
| invalid_request | validation | 422 |
| invalid_interpretation | interpretation | 422 |
| invalid_semantic_query | planning (or execution for explorer arguments) | 422 |
| provider_failed | interpretation | 502 |
| database_unavailable | execution | 503 |
| execution_failed | execution | 502 |

Provider and execution exceptions are chained internally, but raw messages and submitted
credentials are not returned. A valid model response containing an unknown metric reaches
planning and is rejected there. Interpretation failures never silently execute a fallback.

## Extension path

For a new supported aggregate metric, update the YAML and add a result assertion using
known fixture values. For new query operations, update the request contract, logical plan,
resolver, compiler, and cross-engine result tests together. For another business dataset,
provide its semantic model and an already prepared warehouse; do not alter the executor
to seed business data.

Time grouping is represented by `time_grain` on logical dimensions. The output key
`time_period` is shared while branch dimensions retain their actual dataset and Date
column. Only compilation chooses DuckDB DATE_TRUNC or SQLite calendar expressions;
the resolver remains dialect-independent. Service planning uses the configured database
backend, including in plan-only mode.

The Query Inspector renders the returned logical branches directly; it does not infer
plans from SQL or fabricate intermediate row counts. Its planned/executed/failed states
refer to the current query. Skill registries, knowledge graphs, and multi-agent
orchestration remain outside this scope.
