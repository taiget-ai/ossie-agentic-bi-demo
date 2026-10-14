"""Application service: parse -> validate and plan -> execute."""
import os
from dataclasses import asdict
from pathlib import Path

from .catalog import Catalog
from .catalog_errors import PipelineError
from .database import ROOT, Database
from .parsing import llm_parse, rule_parse
from .planner import compile_query
from .planning.compiler import CompiledQuery
from .schemas import LLMOptions, SemanticQuery


class SemanticService:
    def __init__(self, model_path: str | Path | None = None, database: Database | None = None,
                 *, bootstrap_demo: bool | None = None):
        self.catalog = Catalog(model_path or os.getenv("OSSIE_MODEL_PATH") or ROOT / "models/gaming.yaml")
        self.database = database or Database()
        self.bootstrap_demo = database is None if bootstrap_demo is None else bootstrap_demo

    def prepare_database(self):
        """The demo application opts into bootstrap; injected databases do not."""
        if self.bootstrap_demo:
            self.database.ensure_seeded()

    def plan(self, req: SemanticQuery):
        from .analytics import fingerprint, metric_details
        plan = compile_query(self.catalog, req, dialect=self.database.backend)
        return {
            "model_fingerprint": fingerprint(self.catalog),
            "metric_details": [metric_details(self.catalog, m) for m in req.metrics],
            "dialect": self.database.backend,
            "semantic_query": req.model_dump(mode="json"),
            "sql": plan.sql,
            "parameters": plan.parameters,
            "join_path": plan.join_path,
            "logical_plan": asdict(plan.logical_plan),
            "explanation": plan.explanation,
        }

    def query(self, req: SemanticQuery, *, question=None, mode="structured"):
        result = self.plan(req)
        try:
            self.prepare_database()
            rows = self.database.run(CompiledQuery(result["sql"], result["parameters"]))
        except FileNotFoundError as exc:
            raise PipelineError("database_unavailable", "execution",
                                "Database is not initialized.", 503) from exc
        except Exception as exc:
            raise PipelineError("execution_failed", "execution", "Query execution failed.") from exc
        return {"question": question, "mode": mode, **result, "rows": rows}

    def ask(self, question: str, mode="rules", llm: LLMOptions | None = None):
        if mode == "rules":
            try:
                req = rule_parse(question, self.catalog)
            except ValueError as exc:
                raise PipelineError("invalid_interpretation", "interpretation",
                                    "Rule parser could not interpret the question.", 422) from exc
        elif mode == "llm":
            try:
                req = llm_parse(question, self.catalog, options=llm)
            except ValueError as exc:
                raise PipelineError("invalid_interpretation", "interpretation",
                                    "The model returned an invalid semantic query.", 422) from exc
            except Exception as exc:
                raise PipelineError("provider_failed", "interpretation",
                                    "The model provider request failed.") from exc
        else:
            raise ValueError("mode must be rules or llm")
        return self.query(req, question=question, mode=mode)
