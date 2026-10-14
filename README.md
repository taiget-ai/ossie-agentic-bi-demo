# Ossie Agentic BI Demo

**Project release: 1.0.0**

**Independent educational consumer of [Apache Ossie](https://github.com/apache/ossie) semantic metadata, not an official ASF query engine.**

Build governed analytics from natural language using a semantic model instead of asking an LLM to write SQL:

```text
Natural language (offline rules or OpenAI-compatible LLM)
  -> SemanticQuery (approved metrics, dimensions, filters)
  -> Semantic resolver + safe relationship graph
  -> LogicalQueryPlan (one aggregate branch per fact grain)
  -> Restricted expression AST + SQL compiler
  -> DuckDB
  -> Results, source SQL, plan, and dataset preview
```

The LLM **never generates SQL**. Apache Ossie supplies the YAML/JSON **interchange specification**, not a query execution engine. All code that parses, plans, and executes SQL in this repository belongs to this demonstration project.

## Design philosophy

This project is a focused, framework-independent reference implementation of semantic BI.
Its purpose is to make a small, complete query pipeline understandable, extensible, and
verifiable. The core uses ordinary Python functions and data structures; an agent framework
is not required. Ossie metadata supplies the business definitions, the LLM interprets intent,
and deterministic planning and compilation decide how to compute the result.

Correctness takes priority over feature count. DuckDB is the primary execution backend;
SQLite provides an additional cross-engine check. Platform capabilities such as skill
registries, enterprise governance, and agent orchestration belong to a future, independent
SemanticOps project. See [architecture and execution boundaries](docs/architecture.md).

[中文功能使用说明](docs/analytics.zh-CN.md)

## Analytical workflows and bilingual UI

Use the language selector for English or Chinese. The choice is saved locally;
provider credentials are never saved. Offline parsing supports the documented Chinese
metric, country and day/week/month vocabulary; arbitrary Chinese questions can use LLM mode.

- **Period comparison:** choose a SUM/non-distinct COUNT metric and dimension. Leave all
  dates blank for the latest two complete months, or provide both explicit date ranges.
  The engine queries all groups in one database transaction before displaying Top N.
  Remaining groups are reconciled as `other_delta`. Ratios/distinct counts are rejected
  for additive contribution analysis. Contributions describe arithmetic, not causality.
- **Metric explanation:** click a metric value for its formula, fields, time field and
  distinct-count semantics. Ratio metrics show actual numerator and denominator values
  for the current scope. This is a fresh explanation query, not a stored historical result.
- **Drill-down:** click a result row's Drill down action, then a compatible dimension.
  Month/week selections become date filters, intersected with existing date boundaries.
  Business filters are retained. NULL group selections are currently unsupported.
  Breadcrumbs return to earlier results. Incompatible dimensions are explained.
- **Model comparison:** edit a selected metric's candidate expression. Both models are
  validated and run in one read transaction, using all groups before Top N. The original
  model is never overwritten. This first version compares one formula at a time.
- **Reproduction ZIP:** export executes the current structured query again and captures
  source rows in the same transaction. The ZIP includes the model, value vocabulary,
  fingerprints, request, SQL, parameters, JSON/CSV results, data and `replay.py`.
  Extract and run `python replay.py` to verify results in an in-memory database.
  It contains source data for model tables, so it is intended for this local fixture demo.
  It is an export-time snapshot, not a promise that an older screen result is unchanged.

Structured sorting and multi-value example:

```json
{"metrics":["total_stake"],"dimensions":["country"],
 "filters":{"country":["US","JP","FI"]},
 "order_by":[{"field":"total_stake","direction":"desc"}],"limit":5}
```

Workflow endpoints: `POST /api/compare/periods`, `/api/compare/model`,
`/api/metrics/explain`, `/api/drill/options`, `/api/drill`, and `/api/export`.
See the interactive API documentation for their request schemas.

## Run it locally

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

python -m ossie_demo validate
python -m ossie_demo seed                  # explicit first-run seed; otherwise automatic
python -m ossie_demo ask 'Show stake per bettor by country'
python -m ossie_demo ask 'Show total stake and total deposit by country'
uvicorn ossie_demo.api:app --reload --host 127.0.0.1
```

Open **http://127.0.0.1:8000** for the interactive dashboard; browse **http://127.0.0.1:8000/docs** for API documentation.

### Where are the DuckDB data?

The *source data* are committed to the repository, not hidden in generated local files:

```text
data/fixtures/players.csv    36 players across 12 countries (3 distinct players per country)
             games.csv      2 games
             bets.csv      176 bet transactions (one row per bet)
             deposits.csv   89 deposits (one row per deposit)
```

On `seed` or the **first query / data preview**, the application builds a **real DuckDB file** at `data/gaming.duckdb` (unless `OSSIE_DB_PATH` overrides it). This generated binary is intentionally `.gitignore`-excluded, while all four input CSV files remain version controlled. Dates in the fact CSVs are `days_ago` offsets from the seeding date, so the demo's *last 7 days* examples remain relevant when cloned later. The dashboard's **Explore the actual warehouse data** panel shows table names, row counts, and real warehouse rows; **Reset demo data** explicitly rebuilds the sample database.

Inspect the warehouse directly with the DuckDB Python API:

```python
import duckdb
conn = duckdb.connect("data/gaming.duckdb", read_only=True)
print(conn.sql("SHOW TABLES").fetchall())
print(conn.sql("SELECT * FROM deposits LIMIT 5").df())
```

For an additional cross-engine check, an explicitly selected SQLite backend is also available (`OSSIE_DB_BACKEND=sqlite`), but **DuckDB remains the user-facing default**.

Country names and aliases are configured in `models/gaming.values.yaml`, a consumer-specific
sidecar separate from the Ossie specification. The catalog exposes these values to both
the offline parser and LLM. The examples include FI, SG, DE, US, GB, CA, AU, JP, IN, BR,
FR, and ES. Add another entry and matching source data to extend the vocabulary; it is
not a query-engine country whitelist. Short codes are case-sensitive in offline mode
(use `IN` or `India`, not the English word `in`). Multiple country values use parameterized IN filters.

## Configure any OpenAI-compatible model from the page

Change the parser to **OpenAI-compatible LLM**. The dashboard exposes four per-request controls:

| Setting | Examples |
| --- | --- |
| API base URL | `https://api.openai.com/v1`, `https://api.deepseek.com/v1`, `https://dashscope.aliyuncs.com/compatible-mode/v1`, `http://127.0.0.1:11434/v1` |
| Model name | `gpt-4o-mini`, `deepseek-chat`, `qwen-plus`, `llama3.2` |
| API token | Provider-specific secret; optional for local inference endpoints |
| JSON response mode | Uncheck when the endpoint rejects `response_format={"type":"json_object"}` |

Provider presets fill in endpoint/model fields, but you can enter any compatible URL and model ID. The API token is supplied only with that request; the server does not write it to a file, keep it in session state, or return it in a query result. Treat this as a **local developer playground**: passing model URLs from an HTTP request introduces server-side network access (SSRF) risk. **Do not publish the HTTP server unauthenticated** or treat the URL validator as a network firewall. Restrict egress and add authentication/host allowlists before deployment.

For CLI or default provider settings, export environment variables:

```bash
export OPENAI_API_KEY='your-key'               # regular OpenAI usage
export OSSIE_LLM_MODEL='gpt-4o-mini'
# Optional custom provider:
export OSSIE_LLM_BASE_URL='https://api.deepseek.com/v1'
export OSSIE_LLM_API_KEY='your-provider-key'
export OSSIE_LLM_MODEL='deepseek-chat'
python -m ossie_demo ask 'Show total stake by country' --mode llm
```

CLI flags `--llm-base-url` and `--llm-model` override endpoint/model per call. For local Ollama, supply an endpoint and omit the key. Some providers need the JSON-mode checkbox disabled. Compatibility depends on the provider actually supporting OpenAI-style `/chat/completions` requests. The LLM still needs to choose approved Ossie catalog identifiers; invalid selections are rejected by the planner.

**No API key is necessary** in the default offline rules or structured-query modes.

## Aggregation-safe metrics and multiple fact grains

`models/gaming.yaml` is a flat `0.2.0.dev0` Ossie document defining fields, metrics, dimensions, and *many-to-one* relationships. The intentionally different source grains are:

```text
bets:     bet_id     (one row per wager)
    ├── player_id -> players.player_id (many to one)
    └── game_id   -> games.game_id     (many to one)

deposits: deposit_id (one row per deposit)
    └── player_id -> players.player_id (many to one)
```

The following metrics are defined **only in YAML**, not in Python conditionals:

| Metric | Expression | Fact grain |
| --- | --- | --- |
| `total_stake` | `SUM(bets.amount)` | bets |
| `bet_count` | `COUNT(bets.bet_id)` | bets |
| `ngr` | `SUM(bets.amount - bets.payout_amount - bets.bonus_cost)` | bets |
| `unique_bettors` | `COUNT(DISTINCT bets.player_id)` | bets |
| `stake_per_bettor` | `SUM(bets.amount) / COUNT(DISTINCT bets.player_id)` | bets |
| `total_deposit` | `SUM(deposits.amount)` | deposits |
| `deposit_count` | `COUNT(deposits.deposit_id)` | deposits |

The expression parser constructs an **explicit restricted AST** rather than using `eval` or arbitrary string interpolation. Supported metric forms include nested arithmetic over `SUM` / `COUNT` / `AVG`, `COUNT(DISTINCT dataset.column)`, constants, and parentheses. Division is compiled as floating-point division with `NULLIF(denominator, 0)` so empty groups cannot cause divide-by-zero errors. **Adding another supported metric is YAML-only**.

### What makes multi-fact queries safe?

For this request:

```json
{"metrics":["total_stake","total_deposit","stake_per_bettor"],"dimensions":["country"]}
```

The planner **never joins raw `bets` to raw `deposits`**; a player may have multiple bets *and* deposits, which would create many-to-many fanout. Instead, it produces independently aggregated branches:

```text
bets -> JOIN players -> GROUP BY country -> total_stake, stake_per_bettor
                         +
deposits -> JOIN players -> GROUP BY country -> total_deposit
                         |
              UNION dimension keys
                         |
           JOIN aggregates on country
```

Each fact can have its own date field (`bet_date`, `deposit_date`). For a shared date range, the plan applies the filter independently to each branch. Filter parameters are bound, never interpolated. When a metric cannot be grouped by a requested dimension (e.g. `total_deposit` by `game_category`), compilation **fails clearly** rather than inventing a cross-fact JOIN.

### Example: actual deterministic fixture results (three-country excerpt)

```bash
python -m ossie_demo query '{"metrics":["total_stake","total_deposit","stake_per_bettor"],"dimensions":["country"]}'
```

| Country | Total stake | Total deposit | Stake per distinct bettor |
| --- | ---: | ---: | ---: |
| DE | 315 | 200 | 315 |
| FI | 240 | 180 | 240 |
| SG | 420 | 260 | 210 |

Unfiltered grand totals: **total_stake = 29570**, **total_deposit = 31000**. NGR is a synthetic, illustrative accounting definition, not an authoritative industry standard.

## Time grouping and Query Inspector

Use `time_grain` (`day`, `week`, or `month`) independently of business dimensions:

```json
{
  "metrics": ["total_stake", "total_deposit", "stake_per_bettor"],
  "dimensions": ["country"],
  "time_grain": "month",
  "date_from": "2026-09-01",
  "date_to": "2026-10-12"
}
```

Each fact uses its own declared Date dimension (`bets.bet_date`,
`deposits.deposit_date`). Branches filter and aggregate independently, then align on
`time_period` and any business dimensions. Period labels are ISO start dates: days
start on their date, weeks on Monday, and months on the first. Dates are calendar
Date values; timestamp/timezone conversion is not supported. Inclusive date filters
apply before grouping, so boundary periods can be partial. Missing fact values stay
NULL; entirely empty periods are not filled. Ratios are recomputed per group.

A fact must have exactly one declared time dimension. Combining `time_grain` with a
raw date grouping dimension is rejected. `time_period` is reserved for the generated
output key. Omitting `time_grain` preserves the existing query behavior.

Offline examples:

```bash
python -m ossie_demo ask 'Show total stake and total deposit by month'
python -m ossie_demo ask 'Show stake per bettor by week and country'
```

The Query Inspector displays source tables, each branch's time mapping, joins,
predicates, metric formulas, and the final alignment strategy. The complete logical
plan remains available in a disclosure panel. In structured mode, **Inspect plan
only** calls `/api/plan` without executing the query; it replaces any previous result
with a clear not-executed state. The page's separate data explorer may access the
warehouse independently. Errors clear stale query output and show the failure stage.

## Inspect the planner without touching the database

```bash
python -m ossie_demo plan '{"metrics":["total_stake","total_deposit"],"dimensions":["country"]}'
```

The `LogicalQueryPlan` now contains **`branches`** and a **`strategy`** (`single_fact` or `aggregate_then_join`). The compiler turns it into a parameterized SQL query. The logical plan is returned in the API and displayed in the UI.

```text
SemanticQuery
    -> resolve_query (metric roots, compatible dimension paths, predicates)
    -> LogicalQueryPlan (AggregateBranch per fact grain)
    -> compile_sql (restricted aggregate AST + keys reconciliation)
    -> DuckDB
```

## HTTP API

| Endpoint | Action |
| --- | --- |
| `GET /api/model` | Metric / dimension catalog for grounding the parser |
| `POST /api/ask` | Question + parser mode + optional transient LLM settings |
| `POST /api/plan` | Structured request -> logical plan + SQL; no DB or LLM |
| `POST /api/query` | Structured request -> execute and return traced results |
| `GET /api/data` | Warehouse backend, path, table counts |
| `GET /api/data/preview?table=deposits&limit=10` | Whitelisted read-only preview |
| `POST /api/data/seed` | **Destructive** fixture reset (local demo only) |
| `GET /api/health` | Service metadata and database initialization state |

Errors keep the human-readable `detail` field and add a stable envelope:

```json
{
  "detail": "Database is not initialized.",
  "error": {
    "code": "database_unavailable",
    "stage": "execution",
    "message": "Database is not initialized."
  }
}
```

Stages distinguish request validation, interpretation, planning, and execution.
Invalid requests and semantic queries return 422, a missing warehouse returns 503,
and provider/execution failures return 502. Validation and provider failures do not
echo request bodies, credentials, or raw upstream exceptions.

Sample per-request model configuration:

```json
{
  "question": "Show stake per bettor by country",
  "mode": "llm",
  "llm": {
    "base_url": "http://127.0.0.1:11434/v1",
    "model": "llama3.2",
    "api_key": null,
    "json_mode": false
  }
}
```

For quick examples with no LLM:

```bash
python -m ossie_demo ask 'Show total stake and total deposit by country'
python -m ossie_demo query '{"metrics":["stake_per_bettor"],"dimensions":["country"]}'
python scripts/evaluate.py --mode rules
python -m pytest -q
```

## Compatibility and limitations

This remains a **proof of concept**, not a production semantic engine:

- The supported Ossie subset requires direct-column fields, declared unique dimension join targets, simple physical table names, one source dataset *per metric expression*, and a restricted aggregate AST. The Ossie standard itself permits richer expressions and cross-dataset definitions than this consumer supports.
- Multiple metrics over separate fact tables are supported at **shared, reachable dimensions** only. Arbitrary metric-to-metric dependencies, true multilevel dimensional hierarchy reconciliation, slowly changing/as-of joins, drill-across across incompatible grains, user-specific permissions, fiscal calendars, timezone conversion and time-series gap filling are **not** implemented.
- `SUM`, `COUNT`, `AVG`, and `COUNT(DISTINCT ...)` are supported in the restricted expression grammar. No window functions, SQL subqueries, conditional aggregates, median/percentile, custom functions, or general SQL parsing.
- Relationships are trusted metadata: production deployments must additionally check the actual uniqueness constraints and time validity. There are no production-grade row-level policies, budgets, model-usage controls, network controls, or authentication.
- `0.2.0.dev0` is an **unreleased, mutable Apache Ossie specification**. `python -m ossie_demo validate` checks only our supported subset. Use `./scripts/validate_official.sh` (requires an internet connection) to run the upstream Apache Ossie validator for your checkout; pin a commit for reproducible builds.

The automated service tests run against **both real DuckDB and SQLite**, including result assertions for multi-fact queries, ratios, empty aggregates, missing dimension keys, and groups present in only one fact. DuckDB is required for the test suite; these tests do not silently skip it. Live external LLM calls remain a separate, opt-in evaluation.

## Docker

```bash
docker build -t ossie-agentic-bi-demo .
docker run --rm -p 127.0.0.1:8000:8000 ossie-agentic-bi-demo
```

Do **not** publish the demo HTTP port to a public network, especially with configurable outbound LLM URLs and the fixture-reset endpoint.

## License

MIT. See [LICENSE](LICENSE). Contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).
