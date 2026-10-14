# Contributing

Thanks for contributing. This is an educational, independent project, not an Apache Software Foundation project.

1. Open an issue describing the use case and supported Ossie metadata subset.
2. Add a regression test for each new semantic query shape, especially joins and fanout.
3. Keep LLM output constrained to semantic identifiers; never run free-form user/LLM SQL.
4. Run `pytest -q`, `python scripts/evaluate.py --mode rules`, and `python -m ossie_demo validate` before submitting a PR.
5. If changing the Ossie document structure, verify against the upstream draft schema and describe the version.

Avoid committing datasets containing personal information, API keys, secrets, or licensed model weights.
