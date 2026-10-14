"""Start with: uvicorn ossie_demo.api:app --reload"""
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import analytics
from .catalog import SemanticError
from .catalog_errors import PipelineError
from .database import ROOT
from .schemas import (
    AskRequest,
    DrillRequest,
    MetricExplanation,
    ModelComparison,
    PeriodComparison,
    SemanticQuery,
)
from .service import SemanticService


def create_app(service: SemanticService | None = None):
    service = service or SemanticService()
    api = FastAPI(title="Ossie Agentic BI Demo", version="1.0.0",
                  description="Illustrative independent consumer of Apache Ossie metadata")
    api.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")

    @api.get("/")
    def index():
        return FileResponse(ROOT / "web/index.html")

    @api.get("/api/health")
    def health():
        return {"status": "ok", "model": service.catalog.raw["name"],
                "database": {"backend": service.database.backend,
                             "initialized": service.database.path.exists()}}

    @api.get("/api/model")
    def model():
        return service.catalog.public_model()

    def error_response(status, code, stage, message):
        return JSONResponse(status_code=status, content={
            "detail": message,
            "error": {"code": code, "stage": stage, "message": message},
        })

    @api.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Do not echo request bodies: provider settings may contain secrets.
        return error_response(422, "invalid_request", "validation",
                              "Request does not match the API contract.")

    def safe_call(fn, stage="planning"):
        try:
            return fn()
        except PipelineError as exc:
            return error_response(exc.status, exc.code, exc.stage, str(exc))
        except (SemanticError, ValueError, ValidationError) as exc:
            return error_response(422, "invalid_semantic_query", stage, str(exc))
        except FileNotFoundError:
            return error_response(503, "database_unavailable", "execution",
                                  "Database is not initialized.")
        except Exception:  # noqa: BLE001 - redact errors at the public API boundary
            return error_response(502, "execution_failed", stage, "Operation failed.")

    @api.post("/api/plan")
    def plan(request: SemanticQuery):
        return safe_call(lambda: service.plan(request))

    @api.post("/api/query")
    def query(request: SemanticQuery):
        return safe_call(lambda: service.query(request))

    @api.post("/api/ask")
    def ask(request: AskRequest):
        return safe_call(lambda: service.ask(request.question, request.mode, llm=request.llm))

    @api.post('/api/compare/periods')
    def compare_periods(request: PeriodComparison):
        return safe_call(lambda: analytics.period_comparison(service, request))

    @api.post('/api/compare/model')
    def compare_model(request: ModelComparison):
        return safe_call(lambda: analytics.model_comparison(service, request))

    @api.post('/api/metrics/explain')
    def explain_metric(request: MetricExplanation):
        return safe_call(lambda: analytics.explain_value(service, request.query, request.metric))

    @api.post('/api/drill/options')
    def drill_options(request: SemanticQuery):
        return safe_call(lambda: analytics.drill_options(service, request))

    @api.post('/api/drill')
    def drill(request: DrillRequest):
        return safe_call(lambda: service.query(analytics.drill_query(service, request)))

    @api.post('/api/export')
    def export(request: SemanticQuery):
        return safe_call(lambda: Response(analytics.reproduction(service, request),
            media_type='application/zip',
            headers={'Content-Disposition': 'attachment; filename="query-reproduction.zip"'}))

    @api.get("/api/data")
    def data_overview():
        def overview():
            service.prepare_database()
            return service.database.overview()
        return safe_call(overview, "execution")

    @api.get("/api/data/preview")
    def data_preview(table: str = "bets", limit: int = 20):
        def preview():
            service.prepare_database()
            return {"table": table, "rows": service.database.preview(table, limit)}
        return safe_call(preview, "execution")

    @api.post("/api/data/seed")
    def data_seed():
        # Explicit reset only. Web UI warns before calling this destructive demo operation.
        return safe_call(lambda: service.database.seed())

    return api


app = create_app()
