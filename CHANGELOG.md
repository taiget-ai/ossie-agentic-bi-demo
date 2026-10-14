# Changelog

## Unreleased — Analytical workflows and bilingual interface

- Add deterministic period comparison and additive contribution reconciliation before Top N.
- Explain metric AST semantics and real ratio components.
- Add compatible drill-down with preserved filters and period intersections.
- Compare candidate metric expressions on one snapshot without changing saved models.
- Export replayable ZIPs with source snapshots, model fingerprints, SQL, parameters, and results.
- Add parameterized multi-value filters and final-result sorting.
- Add English/Chinese UI, stored language preference, and Chinese offline query vocabulary.

## Unreleased — Expanded market examples

- Remove the two hard-coded provider IP exclusions; retain URL format and embedded-credential validation.
- Add nine markets and synthetic transactions across approximately three months.
- Load country names and aliases from a model sidecar for offline and LLM parsing.
- Avoid matching lowercase English words as country codes and reject multiple country filters explicitly.


## Unreleased — Time grouping and Query Inspector

- Add day, Monday-based week, and calendar month grouping with cross-fact time alignment.
- Compile time expressions for DuckDB and SQLite while retaining physical time fields in each logical branch.
- Extend offline and LLM interpretation contracts with `time_grain`.
- Render branch sources, time mappings, joins, predicates, metrics, and alignment in Query Inspector.
- Add structured plan-only interaction and clear stale results on failure.
- Verify year/month/leap-day boundaries, partial periods, ratios, and absent fact buckets on both engines.

### Reference implementation reliability

- Run service regression tests against DuckDB and SQLite with asserted results.
- Cover empty aggregates, absent fact groups, missing dimension keys, read-only execution, and initialization boundaries.
- Move fixture initialization into `demo_data.py`; make resets transactional.
- Use read-only query connections and opt-in bootstrap for injected databases.
- Share service planning across CLI, API, and execution.
- Add structured error codes and failure stages while preserving `detail`.
- Document design philosophy, extension boundaries, and SemanticOps scope.

## 1.0.0 — OpenAI-compatible providers, seeded DuckDB explorer, and multiple fact grains

- Promote the independent demo project version to 1.0.0 without changing the Apache Ossie specification version.

- Add transient per-request LLM endpoint, model name, token, and JSON-mode settings in API/UI. Include presets for OpenAI, DeepSeek, Qwen/DashScope, OpenRouter, and Ollama; retain environment-based configuration.
- Keep provider tokens out of returned query results and plans. Document local-only network security expectations.
- Commit version-controlled player, game, bet, and deposit CSV fixtures; materialize DuckDB on first use, and expose dataset preview, table counts, and explicit reset in the dashboard/API.
- Parse governed aggregate expressions as a restricted AST. Support `COUNT(DISTINCT ...)`, arithmetic of aggregate results, float-safe division and `NULLIF` guards.
- Add a separate `deposits` fact dataset and metrics; allow metric lists spanning independent fact roots by creating an `AggregateBranch` per grain.
- Aggregate each branch **before** joining on a union of shared group keys; reject dimensions unsupported by a fact's safe relationship graph.
- Support shared date filtering on each fact's declared time dimension.
- Extend offline SQL, API, provider, data explorer, injection, and multi-grain regression tests.

## 0.2.0 — Logical query planning and OpenAI

- Split semantic resolution, safe join-path planning, logical plans, and SQL compilation into separate modules.
- Support multiple metrics from one fact dataset and expose SQL and plan debugging.
- Adopt English-language examples and the standard OpenAI API, replacing provider-specific integrations.
- Introduce `metrics: []` in place of the v0.1 singular `metric` query shape.

## 0.1.0 — Initial governed demo

- Provide an Apache Ossie YAML example, offline semantic parsing, basic SQL queries, FastAPI, and DuckDB.
