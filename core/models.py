"""Shared data models: the AnalysisIntent schema and the objects passed through the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

MetricName = Literal["payment_success_rate", "order_conversion_rate", "successful_gmv", "transaction_count"]
AnalysisType = Literal["summary", "trend", "breakdown", "root_cause", "reconciliation"]
DimensionName = Literal["bank", "payment_method", "merchant_category", "region", "decline_reason", "merchant", "day"]
TimeKind = Literal["last_full_week", "last_n_days", "this_week", "yesterday", "explicit", "unspecified"]


class Filter(BaseModel):
    dimension: DimensionName
    values: list[str]


class TimeSpec(BaseModel):
    kind: TimeKind
    n_days: int | None = Field(description="Only for kind=last_n_days")
    start: str | None = Field(description="YYYY-MM-DD, only for kind=explicit")
    end: str | None = Field(description="YYYY-MM-DD inclusive, only for kind=explicit")


class AnalysisIntent(BaseModel):
    is_supported: bool = Field(description="False if the question needs data or reasoning PaymentLens does not have")
    unsupported_reason: str | None
    metric: MetricName | None
    metric_explicit: bool = Field(description="True only if the user clearly said attempt-level or order-level")
    analysis_type: AnalysisType
    current_period: TimeSpec
    comparison: Literal["previous_period", "none", "explicit"]
    comparison_period: TimeSpec | None
    dimensions: list[DimensionName]
    filters: list[Filter]
    data_source: Literal["trusted", "raw"]
    requested_attributes: list[str] = Field(description="Non-analytical attributes requested, e.g. settlement_account, contact_email, merchant_name")
    ambiguities: list[str] = Field(description="Short notes on anything ambiguous in the question")


# ----------------------------------------------------------------------------- internal

@dataclass
class Period:
    label: str            # "current" / "previous"
    start: date           # inclusive
    end: date             # inclusive

    @property
    def start_ts(self) -> str:
        return f"{self.start:%Y-%m-%d} 00:00:00"

    @property
    def end_ts_exclusive(self) -> str:
        return f"{self.end + timedelta(days=1):%Y-%m-%d} 00:00:00"

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def pretty(self) -> str:
        return f"{self.start:%d %b %Y} - {self.end:%d %b %Y}"


@dataclass
class ResolvedQuery:
    metric: str
    metric_spec: dict
    analysis_type: str
    current: Period
    previous: Period | None
    dimensions: list[str]
    filters: dict[str, list[str]]
    source_table: str
    role: str
    assumptions: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)


@dataclass
class QueryRecord:
    id: str
    purpose: str
    sql: str                  # SQL as built by the compiler (before any role filter is added)
    executed_sql: str         # SQL actually sent to DuckDB
    status: str               # OK / BLOCKED / ERROR / TIMEOUT
    rows: int = 0
    elapsed_ms: float = 0.0
    cache_hit: bool = False
    tables: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    error: str | None = None


@dataclass
class Fact:
    id: str
    text: str
    query_ids: list[str] = field(default_factory=list)


class Hypothesis(BaseModel):
    text: str
    confidence: Literal["low", "medium", "high"]
    evidence: list[str]


class Narrative(BaseModel):
    summary: str
    observed: list[str]
    hypotheses: list[Hypothesis]
    recommendations: list[str]
    generated_by: str = "template"
    grounding: dict = Field(default_factory=dict)


@dataclass
class TraceStep:
    step: str
    component: str
    detail: str
    elapsed_ms: float


@dataclass
class AnalysisResult:
    question: str
    role: str
    status: str = "ANSWERED"   # ANSWERED / DENIED / UNSUPPORTED / BLOCKED / ERROR
    message: str = ""
    intent: AnalysisIntent | None = None
    parser_used: str = ""
    parser_notes: list[str] = field(default_factory=list)
    resolved: ResolvedQuery | None = None
    policy: dict = field(default_factory=dict)
    queries: list[QueryRecord] = field(default_factory=list)
    dq: dict = field(default_factory=dict)
    analysis: dict[str, Any] = field(default_factory=dict)
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    facts: list[Fact] = field(default_factory=list)
    narrative: Narrative | None = None
    confidence: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    trace: list[TraceStep] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
