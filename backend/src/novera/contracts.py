"""Validated in-memory financial observations; no provider or wire-format adapter."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
import re


class Quality(StrEnum):
    PRESENT = "present"
    MISSING = "missing"
    INVALID = "invalid"
    NOT_APPLICABLE = "not_applicable"


class RecordKind(StrEnum):
    INDICATOR = "indicator"
    PRICE = "price"
    STATEMENT = "statement"
    DISTRIBUTION = "distribution"


def _text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")


def _date(value: date, field: str) -> None:
    if type(value) is not date:
        raise ValueError(f"{field} must be a date, not a datetime")


def _timestamp(value: datetime, field: str) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Asset:
    """Stable identifier scoped by namespace; ticker alone is not an identity."""

    namespace: str
    identifier: str

    def __post_init__(self) -> None:
        _text(self.namespace, "namespace")
        _text(self.identifier, "identifier")


@dataclass(frozen=True, slots=True)
class Source:
    provider: str
    reference: str
    rule_version: str
    synthetic: bool

    def __post_init__(self) -> None:
        for field in ("provider", "reference", "rule_version"):
            _text(getattr(self, field), field)
        if type(self.synthetic) is not bool:
            raise ValueError("synthetic must be explicit bool")


@dataclass(frozen=True, slots=True)
class Period:
    start: date
    end: date

    def __post_init__(self) -> None:
        _date(self.start, "start")
        _date(self.end, "end")
        if self.start > self.end:
            raise ValueError("period start must not exceed end")


@dataclass(frozen=True, slots=True)
class Provenance:
    source: Source
    period: Period
    collected_at: datetime
    published_at: datetime | None
    publication_unknown_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, Source) or not isinstance(self.period, Period):
            raise ValueError("source and period must be validated contracts")
        _timestamp(self.collected_at, "collected_at")
        if self.published_at is None:
            _text(self.publication_unknown_reason, "publication_unknown_reason")
        else:
            _timestamp(self.published_at, "published_at")
            if self.publication_unknown_reason is not None:
                raise ValueError("known publication must not have unknown reason")
            if self.published_at > self.collected_at:
                raise ValueError("publication must not exceed collection")


@dataclass(frozen=True, slots=True)
class Observation:
    """A normalized scalar: absent/invalid values never become numeric zero."""

    asset: Asset
    kind: RecordKind
    metric: str
    value: Decimal | None
    quality: Quality
    unit: str
    currency: str | None
    provenance: Provenance
    reason: str | None = None
    statement_scope: str | None = None
    statement_basis: str | None = None
    revision: str | None = None
    distribution_type: str | None = None
    tax_basis: str | None = None
    ex_date: date | None = None
    payment_date: date | None = None
    adjustment: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.asset, Asset) or not isinstance(self.provenance, Provenance):
            raise ValueError("asset and provenance must be validated contracts")
        if not isinstance(self.kind, RecordKind) or not isinstance(self.quality, Quality):
            raise ValueError("kind and quality must be enum members")
        _text(self.metric, "metric")
        _text(self.unit, "unit")
        if self.currency is not None and (
            not isinstance(self.currency, str) or not re.fullmatch(r"[A-Z]{3}", self.currency)
        ):
            raise ValueError("currency must be a three-letter uppercase code or None")
        if self.unit in ("currency", "currency/share"):
            _text(self.currency, "currency")
        if self.quality is Quality.PRESENT:
            if not isinstance(self.value, Decimal) or not self.value.is_finite():
                raise ValueError("present value must be a finite Decimal")
            if self.reason is not None:
                raise ValueError("present value must not have an absence reason")
        else:
            if self.value is not None:
                raise ValueError("non-present value must be None")
            _text(self.reason, "reason")
        for field in ("statement_scope", "statement_basis", "revision", "distribution_type",
                      "tax_basis", "adjustment"):
            if getattr(self, field) is not None:
                _text(getattr(self, field), field)
        for field in ("ex_date", "payment_date"):
            if getattr(self, field) is not None:
                _date(getattr(self, field), field)
        if self.kind is RecordKind.PRICE:
            _text(self.currency, "currency")
            _text(self.adjustment, "adjustment")
            if self.unit != "currency/share":
                raise ValueError("price unit must be currency/share")
            if self.value is not None and self.value < 0:
                raise ValueError("price cannot be negative")
            if self.provenance.period.start != self.provenance.period.end:
                raise ValueError("price must reference a single date")
        elif self.adjustment is not None:
            raise ValueError("adjustment is specific to price")
        statement_fields = (self.statement_scope, self.statement_basis, self.revision)
        if self.kind is RecordKind.STATEMENT:
            if self.statement_scope not in ("consolidated", "individual"):
                raise ValueError("statement_scope must be consolidated or individual")
            if self.statement_basis not in ("instant", "duration", "year_to_date"):
                raise ValueError("statement_basis must describe accounting period basis")
            _text(self.revision, "revision")
            if self.statement_basis == "instant" and (
                self.provenance.period.start != self.provenance.period.end
            ):
                raise ValueError("instant statement must reference a single date")
        elif any(v is not None for v in statement_fields):
            raise ValueError("statement metadata is specific to statements")
        distribution_fields = (self.distribution_type, self.tax_basis, self.ex_date, self.payment_date)
        if self.kind is RecordKind.DISTRIBUTION:
            _text(self.currency, "currency")
            _text(self.distribution_type, "distribution_type")
            if self.tax_basis not in ("gross", "net", "unknown"):
                raise ValueError("tax_basis must be gross, net or unknown")
            if self.unit != "currency/share":
                raise ValueError("distribution unit must be currency/share")
            # Event dates may be unknown; no date is inferred from collection time.
        elif any(v is not None for v in distribution_fields):
            raise ValueError("distribution metadata is specific to distributions")
