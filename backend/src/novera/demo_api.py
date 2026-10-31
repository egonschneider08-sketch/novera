"""Local-only FastAPI v1 facade for Novera's three *fictional* research scenarios.

No provider adapters, credentials, live HTTP clients, database files or user
accounts are created. This is a development laboratory, NOT a production API.
The explicit CLI binds to 127.0.0.1; do not expose this app to public traffic.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from novera.research_compare import compare_scenarios, comparison_csv, comparison_json
from novera.research_demo import DISCLAIMER, SCENARIOS, report_json, run_scenario

DecimalText = Annotated[
    str,
    StringConstraints(pattern=r"^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$"),
]
HashText = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
ScenarioId = Literal["complete", "expensive", "incomplete"]
State = Literal["pass", "fail", "unknown"]
Quality = Literal["present", "missing", "invalid", "not_applicable"]


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DateRange(StrictRecord):
    start: str
    end: str


class AssetOut(StrictRecord):
    namespace: Literal["novera.demo"]
    identifier: str


class SourceOut(StrictRecord):
    provider: Literal["novera-synthetic-fixture"]
    reference: Annotated[
        str,
        StringConstraints(pattern=r"^https://example\.invalid/novera/research/"),
    ]
    rule_version: str
    synthetic: Literal[True]


class ObservationOut(StrictRecord):
    record_key: str
    logical_id: HashText
    version: int
    content_id: HashText
    receipt_id: HashText
    kind: str
    metric: str
    value: DecimalText | None
    quality: Quality
    reason: str | None
    unit: str
    currency: str | None
    reference_period: DateRange
    source: SourceOut
    collected_at: str
    published_at: str | None
    publication_unknown_reason: str | None

    @model_validator(mode="after")
    def quality_consistency(self) -> ObservationOut:
        if (self.quality == "present") != (self.value is not None):
            raise ValueError("observation quality and value disagree")
        if self.version < 1:
            raise ValueError("invalid observation version")
        return self


class CriterionOut(StrictRecord):
    name: str
    state: State
    reason: str


class MetricOut(StrictRecord):
    name: str
    value: DecimalText | None
    quality: Literal["present", "missing"]
    unit: str
    currency: str | None
    period: DateRange
    reason: str

    @model_validator(mode="after")
    def quality_consistency(self) -> MetricOut:
        if (self.quality == "present") != (self.value is not None):
            raise ValueError("metric quality and value disagree")
        return self


class CoverageOut(StrictRecord):
    source: Literal["novera-synthetic-fixture"]
    synthetic: Literal[True]
    start: str
    end: str
    collected_at: str
    published_at: str | None
    complete_by_fixture: bool


class StrategyOut(StrictRecord):
    methodology: str
    rule_version: str
    state: State
    as_of: str
    synthetic: Literal[True]
    coverage: CoverageOut | None
    metrics: list[MetricOut]
    criteria: list[CriterionOut]


class ReportOut(StrictRecord):
    schema_version: Literal["novera-synthetic-research-v1"] = Field(alias="schema")
    scenario: ScenarioId
    label: str
    asset: AssetOut
    as_of: str
    synthetic: Literal[True]
    disclaimer: str
    share_basis: str
    dividend_coverage_certified_by_fixture: bool
    observations: list[ObservationOut]
    strategies: list[StrategyOut]


class ComparisonOut(StrictRecord):
    schema_version: Literal["novera-synthetic-comparison-v1"] = Field(alias="schema")
    synthetic: Literal[True]
    disclaimer: str
    ordering: Literal["user_selection_not_investment_ranking"]
    total_scenarios: int
    reports: list[ReportOut]


class ScenarioItem(StrictRecord):
    id: ScenarioId
    asset_id: str
    label: str
    synthetic: Literal[True]


class CatalogOut(StrictRecord):
    api_version: Literal["v1"]
    synthetic: Literal[True]
    disclaimer: str
    scenarios: list[ScenarioItem]


class HealthOut(StrictRecord):
    status: Literal["ok"]
    api_version: Literal["v1"]
    data_mode: Literal["synthetic-only"]


def create_app() -> FastAPI:
    """Build an HTTP adapter for already validated, immutable lab reports."""
    application = FastAPI(
        title="Novera — API de laboratório fictício",
        description="Somente cenários LAB; nenhum dado de mercado ou serviço de produção.",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )

    @application.middleware("http")
    async def policy_headers(request: Request, call_next):
        # No query parameter has an approved meaning in this read-only v1 API.
        if request.scope.get("query_string"):
            response = JSONResponse(
                status_code=400,
                content={"detail": "Parâmetros de consulta não são aceitos nesta API."},
            )
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Robots-Tag"] = "noindex"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @application.get("/api/v1/demo/health", response_model=HealthOut, tags=["lab"])
    def health() -> HealthOut:
        """Health of this local fixture facade, NOT of brapi or BCB."""
        return HealthOut(status="ok", api_version="v1", data_mode="synthetic-only")

    @application.get("/api/v1/demo/scenarios", response_model=CatalogOut, tags=["lab"])
    def scenarios() -> CatalogOut:
        return CatalogOut(
            api_version="v1",
            synthetic=True,
            disclaimer=DISCLAIMER,
            scenarios=[
                ScenarioItem(id=key, asset_id=value[0], label=value[1], synthetic=True)
                for key, value in SCENARIOS.items()
            ],
        )

    @application.get(
        "/api/v1/demo/scenarios/{scenario}",
        response_model=ReportOut,
        tags=["lab"],
    )
    def single_report(scenario: str) -> ReportOut:
        if scenario not in SCENARIOS:
            raise HTTPException(status_code=404, detail="Cenário fictício não encontrado.")
        return ReportOut.model_validate(report_json(run_scenario(scenario)))

    @application.get("/api/v1/demo/comparison", response_model=ComparisonOut, tags=["lab"])
    def comparison() -> ComparisonOut:
        return ComparisonOut.model_validate(comparison_json(compare_scenarios()))

    @application.get("/api/v1/demo/comparison.csv", tags=["lab"])
    def csv_export() -> Response:
        return Response(
            content=comparison_csv(compare_scenarios()),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="novera-lab-ficticio.csv"',
            },
        )

    return application


app = create_app()


def main() -> None:
    """Run only on loopback, never as an externally exposed trading-data service."""
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
