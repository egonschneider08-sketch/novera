"""Explicit, opt-in orchestration of validated provider observations into SQLite.

No provider is contacted on import or construction. The caller must explicitly
enable execution; unit and integration tests must inject httpx.MockTransport.
This does not grant licensing or constitute a production collection service.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from novera.bcb import BcbAdapter
from novera.brapi import BrapiAdapter, BrapiInstrument
from novera.contracts import Observation, Period, RecordKind
from novera.http import AccessContext, CachePolicy, Freshness, JsonEnvelope
from novera.storage import ObservationStore, StorageScope, StoredObservation

MAX_TASKS = 16


class PipelineError(RuntimeError):
    """Sanitized orchestration or policy failure, without provider payloads or tokens."""


@dataclass(frozen=True, slots=True)
class QuoteRequest:
    """One verified instrument; bearer token never appears in repr or storage."""

    instrument: BrapiInstrument
    token: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if type(self.instrument) is not BrapiInstrument:
            raise ValueError("verified brapi instrument required")
        if self.token is not None and (
            not isinstance(self.token, str)
            or not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", self.token)
        ):
            raise ValueError("invalid bearer credential format")


@dataclass(frozen=True, slots=True)
class SgsRequest:
    """One bounded SGS 432 window; missing calendar dates are never filled."""

    period: Period

    def __post_init__(self) -> None:
        if type(self.period) is not Period:
            raise ValueError("validated SGS period required")


@dataclass(frozen=True, slots=True)
class TaskReport:
    provider: str
    freshness: Freshness
    fetched_at: datetime
    received: int
    unreturned_dates: tuple[date, ...] = ()


@dataclass(frozen=True, slots=True)
class PipelineRun:
    """All write receipts and non-numeric provider outcomes; not a trading signal."""

    records: tuple[StoredObservation, ...]
    tasks: tuple[TaskReport, ...]


def _validate_observation(
    item: Observation, envelope: JsonEnvelope, provider: str
) -> None:
    if (
        type(item) is not Observation
        or item.provenance.source.provider != provider
        or item.provenance.source.synthetic is not True
        or item.provenance.collected_at != envelope.fetched_at
    ):
        raise PipelineError("untrusted provider observation or collection timestamp")


def _ensure_fresh(envelope: JsonEnvelope) -> None:
    # FRESH means a validated HTTP cache hit, not a new economic observation.
    # STALE means transport failure and must never be silently re-ingested.
    if envelope.freshness not in (Freshness.NETWORK, Freshness.FRESH):
        raise PipelineError("stale or unknown freshness cannot enter the pipeline")


class FinancialPipeline:
    """A single explicit run: fetch every task, then commit all observations atomically.

    Synthetic lab only. A synthetic label is NOT a network safety boundary: the
    explicit enabled flag is a deliberate opt-in, not permission to use live data.
    The application that constructs clients remains responsible for network
    isolation, provider terms, authorization and rate limits.
    """

    def __init__(
        self,
        store: ObservationStore,
        *,
        context: AccessContext,
        brapi: BrapiAdapter | None = None,
        bcb: BcbAdapter | None = None,
        enabled: bool = False,
    ):
        if type(store) is not ObservationStore or type(context) is not AccessContext:
            raise PipelineError("validated storage and access context required")
        if type(enabled) is not bool:
            raise PipelineError("enabled must be explicit bool")
        try:
            AccessContext(context.tenant, context.entitlement, context.credential_revision)
            scope = StorageScope(context.tenant, context.entitlement, context.credential_revision)
        except (ValueError, TypeError):
            raise PipelineError("invalid access context") from None
        if store.scope != scope or store.synthetic is not True:
            raise PipelineError("storage scope mismatch or real-data mode unsupported")
        if (
            (brapi is not None and (type(brapi) is not BrapiAdapter or brapi.synthetic is not True))
            or (bcb is not None and (type(bcb) is not BcbAdapter or bcb.synthetic is not True))
            or (brapi is None and bcb is None)
        ):
            raise PipelineError("at least one synthetic, verified adapter required")
        self._store = store
        self._context = context
        self._brapi = brapi
        self._bcb = bcb
        self._enabled = enabled

    def run(
        self,
        requests: Sequence[QuoteRequest | SgsRequest],
        *,
        cache_policy: CachePolicy = CachePolicy(enabled=False),
    ) -> PipelineRun:
        """Run validated tasks in order; provider failure means zero database writes.

        Does not schedule, authorize external data redistribution or infer
        financial availability. A batch may have zero observed SGS rows.
        """
        if not self._enabled:
            raise PipelineError("provider requests are disabled by default")
        if type(cache_policy) is not CachePolicy or cache_policy.allow_stale:
            raise PipelineError("stale policy is forbidden for pipeline ingestion")
        if not isinstance(requests, (tuple, list)) or not 0 < len(requests) <= MAX_TASKS:
            raise PipelineError("explicit bounded request sequence required")
        if self._store.scope != StorageScope(
            self._context.tenant, self._context.entitlement, self._context.credential_revision
        ) or self._store.synthetic is not True:
            raise PipelineError("storage access context changed")

        # Preflight the whole batch before any provider is contacted.
        for task in requests:
            if type(task) is QuoteRequest:
                if self._brapi is None:
                    raise PipelineError("brapi adapter unavailable")
                task.__post_init__()
            elif type(task) is SgsRequest:
                if self._bcb is None:
                    raise PipelineError("BCB adapter unavailable")
                task.__post_init__()
                if (task.period.end - task.period.start).days >= 366:
                    raise PipelineError("SGS period exceeds maximum inclusive window")
            else:
                raise PipelineError("unsupported pipeline request type")

        pending: list[tuple[str, Observation]] = []
        reports: list[TaskReport] = []
        for task in requests:
            if isinstance(task, QuoteRequest):
                assert self._brapi is not None
                result = self._brapi.quote(
                    task.instrument,
                    context=self._context,
                    token=task.token,
                    cache_policy=cache_policy,
                )
                _ensure_fresh(result)
                observation = result.data.price
                _validate_observation(observation, result, "brapi")
                if (
                    observation.kind is not RecordKind.PRICE
                    or observation.metric != "regular_market_price"
                    or observation.asset != task.instrument.asset
                    or result.data.symbol != task.instrument.symbol
                ):
                    raise PipelineError("unexpected brapi observation identity")
                snapshot_at = result.data.market_at.astimezone(timezone.utc).isoformat()
                key = f"brapi:quote:{task.instrument.symbol}:{snapshot_at}"
                pending.append((key, observation))
                reports.append(TaskReport("brapi", result.freshness, result.fetched_at, 1))
            else:
                assert self._bcb is not None
                result = self._bcb.selic_target(
                    task.period, context=self._context, cache_policy=cache_policy
                )
                _ensure_fresh(result)
                if result.data.requested_period != task.period:
                    raise PipelineError("BCB response window mismatch")
                for observation in result.data.observations:
                    _validate_observation(observation, result, "bcb")
                    if (
                        observation.asset.namespace != "bcb.sgs"
                        or observation.asset.identifier != "432"
                        or observation.kind is not RecordKind.INDICATOR
                        or observation.metric != "selic_target"
                    ):
                        raise PipelineError("unexpected SGS indicator identity")
                    key = f"bcb:sgs:432:{observation.provenance.period.start.isoformat()}"
                    pending.append((key, observation))
                reports.append(
                    TaskReport(
                        "bcb", result.freshness, result.fetched_at,
                        len(result.data.observations), result.data.unreturned_dates,
                    )
                )

        # One atomic transaction for all providers; failed fetches never leave
        # half-complete snapshots in the local repository.
        records = self._store.ingest_many(pending)
        return PipelineRun(records, tuple(reports))
