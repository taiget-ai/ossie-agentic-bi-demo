# Committed demonstration data

These are **fictional** deterministic fixtures. `days_ago` in the fact files is an offset from the date on which `seed` is run, not a SQL column. The seed materializes it as `bet_date` or `deposit_date`.

The four files intentionally contain multiple bet and deposit transactions for the same player. Never row-level JOIN `bets` with `deposits` on `player_id`: that inflates both measures. The logical planner first aggregates each fact independently and then joins aggregate results on compatible shared dimensions.

The SQLite test database and generated DuckDB file are not committed. Run `python -m ossie_demo seed` to materialize `data/gaming.duckdb` on a machine with the DuckDB package installed, or open the web UI and let first-use initialization create it.

The expanded dataset contains 13 players in 12 countries, 84 bets, and 43 deposits.
New markets have eight bets and four deposits each, spread across 80 days for time-grouping
examples. All amounts and transactions are synthetic. Unfiltered totals are 16455 stake
and 18190 deposit. The original small three-country subset remains the hand-calculated
regression baseline; separate integration tests exercise the full expanded dataset.
Country labels and aliases live in `models/gaming.values.yaml`.
