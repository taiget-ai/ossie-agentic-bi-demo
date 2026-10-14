"""Small CLI; usage: python -m ossie_demo --help (or ossie-demo)."""
import argparse
import json
import os
from pathlib import Path

from .catalog import Catalog
from .database import ROOT, Database
from .schemas import LLMOptions, SemanticQuery
from .service import SemanticService


def main(argv=None):
    p = argparse.ArgumentParser(description="Apache Ossie + Agentic BI demo")
    p.add_argument("--model", type=Path, default=Path(os.getenv("OSSIE_MODEL_PATH", str(ROOT / "models/gaming.yaml"))))
    p.add_argument("--db", type=Path, default=None)
    p.add_argument("--backend", choices=["duckdb", "sqlite"], default=None)
    commands = p.add_subparsers(dest="cmd", required=True)
    commands.add_parser("seed", help="create deterministic demonstration data")
    commands.add_parser("model", help="show metric and dimension vocabulary")
    v = commands.add_parser("validate", help="validate supported subset; optionally official JSON schema")
    v.add_argument("--schema", type=Path, default=None)
    ask = commands.add_parser("ask", help="natural language -> semantic query -> SQL -> rows")
    ask.add_argument("question")
    ask.add_argument("--mode", choices=["rules", "llm"], default="rules")
    ask.add_argument("--llm-base-url", default=None, help="OpenAI-compatible API base URL")
    ask.add_argument("--llm-model", default=None, help="provider model ID")
    ask.add_argument("--llm-no-json-mode", action="store_true", help="omit response_format for limited servers")
    q = commands.add_parser("query", help="run a structured semantic query JSON")
    q.add_argument("json_request", help='e.g. {"metrics":["ngr"],"dimensions":["country"]}')
    plan = commands.add_parser("plan", help="resolve logical plan and SQL without a database")
    plan.add_argument("json_request", help='e.g. {"metrics":["ngr"],"dimensions":["country"]}')
    args = p.parse_args(argv)
    catalog = Catalog(args.model)
    db = Database(args.db, args.backend)
    if args.cmd == "seed":
        result = db.seed()
    elif args.cmd == "model":
        result = catalog.public_model()
    elif args.cmd == "validate":
        if args.schema:
            import jsonschema
            schema = json.loads(args.schema.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(catalog.raw)
        result = {"valid": True, "model": catalog.raw["name"],
                  "note": "subset validator; use upstream Apache Ossie validator for full checks"}
    elif args.cmd == "plan":
        result = SemanticService(args.model, database=db).plan(
            SemanticQuery.model_validate(json.loads(args.json_request)))
    else:
        service = SemanticService(model_path=args.model, database=db, bootstrap_demo=True)
        if args.cmd == "ask":
            result = service.ask(args.question, args.mode,
                                 llm=LLMOptions(base_url=args.llm_base_url,
                                                model=args.llm_model,
                                                json_mode=not args.llm_no_json_mode))
        else:
            result = service.query(SemanticQuery.model_validate(json.loads(args.json_request)))
    print(json.dumps(result, indent=2, ensure_ascii=True, default=str))
    return result
