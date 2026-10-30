"""Versioned, tenant-scoped SQLite repository for validated financial observations.

No collection, network, implicit database creation or destructive migrations occur here.
One store instance/connection is intended for one thread and one trusted access scope.
"""

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from novera.contracts import (
    Asset,
    Observation,
    Period,
    Provenance,
    Quality,
    RecordKind,
    Source,
)

APPLICATION_ID = 0x4E4F5652  # NOVR
SCHEMA_VERSION = 1
MAX_RECORDS_PER_BATCH = 10_000


class StorageError(RuntimeError):
    """Sanitized persistence error; never contains a payload or a provider response."""


@dataclass(frozen=True, slots=True)
class StorageScope:
    """Opaque non-secret identity supplied by the application's authorization layer."""

    tenant: str
    entitlement: str
    credential_revision: str

    def __post_init__(self) -> None:
        for item in (self.tenant, self.entitlement, self.credential_revision):
            if not isinstance(item, str) or not 0 < len(item) <= 256 or not item.strip():
                raise ValueError("scope requires non-empty, bounded, opaque identifiers")
            if any(ord(char) < 32 for char in item):
                raise ValueError("scope identifiers cannot contain control characters")


@dataclass(frozen=True, slots=True)
class StoredObservation:
    logical_id: str
    record_key: str
    version: int
    content_id: str
    receipt_id: str
    observation: Observation


_SCHEMA = (
    """CREATE TABLE versions (
    scope TEXT NOT NULL, synthetic INTEGER NOT NULL CHECK(synthetic IN (0,1)),
    logical_id TEXT NOT NULL, record_key TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version >= 1), content_id TEXT NOT NULL,
    economic TEXT NOT NULL, namespace TEXT NOT NULL, asset TEXT NOT NULL,
    kind TEXT NOT NULL, metric TEXT NOT NULL, provider TEXT NOT NULL,
    period_start TEXT NOT NULL, period_end TEXT NOT NULL,
    PRIMARY KEY(scope,synthetic,logical_id,version),
    UNIQUE(scope,synthetic,logical_id,content_id)
)""",
    """CREATE TABLE collections (
    scope TEXT NOT NULL, synthetic INTEGER NOT NULL CHECK(synthetic IN (0,1)),
    logical_id TEXT NOT NULL, version INTEGER NOT NULL,
    receipt_id TEXT NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY(scope,synthetic,logical_id,receipt_id),
    FOREIGN KEY(scope,synthetic,logical_id,version)
      REFERENCES versions(scope,synthetic,logical_id,version)
)""",
    """CREATE INDEX query_versions ON versions
    (scope,synthetic,namespace,asset,kind,metric,period_start,period_end)""",
)


def _json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identifier(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 0 < len(value) <= 256
        or not value.strip()
        or any(ord(char) < 32 for char in value)
    ):
        raise StorageError("invalid stable event identifier")
    return value


def _safe_reference(reference: str) -> None:
    """Only allow a strictly public HTTPS reference; never persist credential URLs."""
    try:
        url = urlsplit(reference)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.fragment
            or any(ord(c) < 32 for c in reference)
        ):
            raise ValueError
        params = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True)
        if len(params) != len({key for key, _ in params}):
            raise ValueError
        for key, value in params:
            if key == "symbols" and re.fullmatch(r"[A-Z0-9]{4}[0-9]{1,2}", value):
                continue
            if key == "formato" and value == "json":
                continue
            if key in ("dataInicial", "dataFinal") and re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):
                continue
            raise ValueError
        if url.query and not params:
            raise ValueError
    except (TypeError, ValueError):
        raise StorageError("source reference must be a public HTTPS URL") from None


def _wire(value: Observation) -> dict:
    """Explicit, lossless schema: financial decimals are strings, never floats."""
    # A frozen dataclass can still be tampered with via object.__setattr__.
    # Reconstruct the contract at every trust boundary rather than trust its type.
    try:
        assert type(value) is Observation
        clean = Observation(**{f.name: getattr(value, f.name) for f in fields(Observation)})
        assert type(clean.asset) is Asset and type(clean.provenance) is Provenance
        Asset(**asdict(clean.asset))
        source = clean.provenance.source
        assert type(source) is Source and type(clean.provenance.period) is Period
        Source(**asdict(source))
        Period(**asdict(clean.provenance.period))
        Provenance(**{f.name: getattr(clean.provenance, f.name) for f in fields(Provenance)})
        _safe_reference(source.reference)
        assert type(source.synthetic) is bool
        result = {
            "asset": asdict(clean.asset),
            "kind": clean.kind.value,
            "metric": clean.metric,
            "value": str(clean.value) if clean.value is not None else None,
            "quality": clean.quality.value,
            "unit": clean.unit,
            "currency": clean.currency,
            "reason": clean.reason,
            "statement_scope": clean.statement_scope,
            "statement_basis": clean.statement_basis,
            "revision": clean.revision,
            "distribution_type": clean.distribution_type,
            "tax_basis": clean.tax_basis,
            "ex_date": clean.ex_date.isoformat() if clean.ex_date is not None else None,
            "payment_date": clean.payment_date.isoformat()
            if clean.payment_date is not None
            else None,
            "adjustment": clean.adjustment,
            "provenance": {
                "source": asdict(source),
                "period": {
                    "start": clean.provenance.period.start.isoformat(),
                    "end": clean.provenance.period.end.isoformat(),
                },
                "collected_at": clean.provenance.collected_at.isoformat(),
                "published_at": (
                    clean.provenance.published_at.isoformat()
                    if clean.provenance.published_at is not None
                    else None
                ),
                "publication_unknown_reason": clean.provenance.publication_unknown_reason,
            },
        }
        _json(result)
        return result
    except (AssertionError, ValueError, TypeError, AttributeError, OverflowError):
        raise StorageError("invalid observation contract or unsafe metadata") from None


def _decode(raw: str) -> Observation:
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {
            "asset",
            "kind",
            "metric",
            "value",
            "quality",
            "unit",
            "currency",
            "reason",
            "statement_scope",
            "statement_basis",
            "revision",
            "distribution_type",
            "tax_basis",
            "ex_date",
            "payment_date",
            "adjustment",
            "provenance",
        }:
            raise ValueError
        prov = payload.pop("provenance")
        source = Source(**prov["source"])
        period = Period(
            date.fromisoformat(prov["period"]["start"]), date.fromisoformat(prov["period"]["end"])
        )
        provenance = Provenance(
            source=source,
            period=period,
            collected_at=datetime.fromisoformat(prov["collected_at"]),
            published_at=(
                datetime.fromisoformat(prov["published_at"])
                if prov["published_at"] is not None
                else None
            ),
            publication_unknown_reason=prov["publication_unknown_reason"],
        )
        item = Observation(
            **{
                **payload,
                "asset": Asset(**payload["asset"]),
                "kind": RecordKind(payload["kind"]),
                "value": (Decimal(payload["value"]) if payload["value"] is not None else None),
                "quality": Quality(payload["quality"]),
                "ex_date": date.fromisoformat(payload["ex_date"]) if payload["ex_date"] else None,
                "payment_date": date.fromisoformat(payload["payment_date"])
                if payload["payment_date"]
                else None,
                "provenance": provenance,
            }
        )
        if _wire(item) != {**payload, "provenance": prov}:
            raise ValueError
        return item
    except (TypeError, ValueError, KeyError, AttributeError, ArithmeticError, StorageError):
        raise StorageError("stored data integrity failure") from None


def _economic(payload: str) -> str:
    body = json.loads(payload)
    body["provenance"]["collected_at"] = None
    body["provenance"]["source"]["reference"] = None
    return _json(body)


def _logical(scope: str, synthetic: int, key: str, observation: Observation) -> str:
    return _digest(
        _json(
            [
                SCHEMA_VERSION,
                scope,
                synthetic,
                key,
                asdict(observation.asset),
                observation.kind.value,
                observation.metric,
                observation.provenance.source.provider,
            ]
        )
    )


class ObservationStore:
    """Single-thread, scope-fixed repository. Construct with memory() or local()."""

    def __init__(self, connection: sqlite3.Connection, scope: StorageScope, synthetic: bool):
        if type(scope) is not StorageScope or type(synthetic) is not bool:
            connection.close()
            raise StorageError("explicit trusted scope and synthetic flag required")
        scope.__post_init__()
        self._db = connection
        self._scope = _json(asdict(scope))
        self._synthetic = int(synthetic)
        self._closed = False
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA synchronous=FULL")

    @classmethod
    def memory(cls, *, scope: StorageScope, synthetic: bool) -> "ObservationStore":
        store = cls(sqlite3.connect(":memory:", isolation_level=None), scope, synthetic)
        store._initialize()
        return store

    @classmethod
    def local(
        cls, path: Path, *, scope: StorageScope, synthetic: bool, create: bool = False
    ) -> "ObservationStore":
        """Open an absolute local file. Creation is exclusive; parents are never created."""
        path = Path(path)
        if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
            raise StorageError("absolute local database path required")
        if any(item.is_symlink() or item.is_junction() for item in (path, *path.parents)):
            raise StorageError("linked database paths are unsupported")
        if type(scope) is not StorageScope or type(synthetic) is not bool:
            raise StorageError("explicit trusted scope and synthetic flag required")
        scope.__post_init__()
        if create:
            with path.open("xb"):
                pass
        # URI mode=rw means a typo/path race cannot create a fresh database.
        db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=5)
        store = cls(db, scope, synthetic)
        try:
            if create:
                store._initialize()
            store._check_schema()
            return store
        except BaseException:
            store.close()
            raise StorageError("unsupported or invalid storage schema") from None

    def _initialize(self) -> None:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            for stmt in _SCHEMA:
                self._db.execute(stmt)
            self._db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise

    def _check_schema(self) -> None:
        if (
            self._db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
            or self._db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION
        ):
            raise StorageError("unsupported storage schema")
        actual = {
            row[0]
            for row in self._db.execute(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
            )
        }
        if actual != set(_SCHEMA):
            raise StorageError("unexpected storage schema")

    def close(self) -> None:
        if not self._closed:
            self._db.close()
            self._closed = True

    def __enter__(self) -> "ObservationStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def ingest(self, record_key: str, observation: Observation) -> StoredObservation:
        return self.ingest_many(((record_key, observation),))[0]

    def ingest_many(
        self, records: Iterable[tuple[str, Observation]]
    ) -> tuple[StoredObservation, ...]:
        """One transaction; same economic version can have multiple collection receipts."""
        results: list[StoredObservation] = []
        try:
            self._db.execute("BEGIN IMMEDIATE")
            for key, observation in records:
                if len(results) >= MAX_RECORDS_PER_BATCH:
                    raise StorageError("batch exceeds safety limit")
                _identifier(key)
                wire = _wire(observation)
                if observation.provenance.source.synthetic != bool(self._synthetic):
                    raise StorageError("synthetic scope mismatch")
                payload = _json(wire)
                economic = _economic(payload)
                content_id = _digest(economic)
                logical_id = _logical(self._scope, self._synthetic, key, observation)
                receipt_id = _digest(_json([logical_id, payload]))
                prefix = (self._scope, self._synthetic, logical_id)
                existing = self._db.execute(
                    "SELECT version FROM versions WHERE scope=? AND synthetic=? "
                    "AND logical_id=? AND content_id=?",
                    (*prefix, content_id),
                ).fetchone()
                if existing:
                    version = existing[0]
                else:
                    version = self._db.execute(
                        "SELECT COALESCE(MAX(version),0)+1 FROM versions "
                        "WHERE scope=? AND synthetic=? AND logical_id=?",
                        prefix,
                    ).fetchone()[0]
                    period = observation.provenance.period
                    self._db.execute(
                        "INSERT INTO versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            *prefix,
                            key,
                            version,
                            content_id,
                            economic,
                            observation.asset.namespace,
                            observation.asset.identifier,
                            observation.kind.value,
                            observation.metric,
                            observation.provenance.source.provider,
                            period.start.isoformat(),
                            period.end.isoformat(),
                        ),
                    )
                self._db.execute(
                    "INSERT INTO collections VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(scope,synthetic,logical_id,receipt_id) DO NOTHING",
                    (*prefix, version, receipt_id, payload),
                )
                results.append(
                    StoredObservation(logical_id, key, version, content_id, receipt_id, observation)
                )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise StorageError("ingestion failed; batch rolled back") from None
        except BaseException:
            self._db.rollback()
            raise
        return tuple(results)

    def query(
        self,
        *,
        asset: Asset,
        kind: RecordKind,
        metric: str,
        period: Period,
        version: int | None = None,
        provider: str | None = None,
    ) -> tuple[StoredObservation, ...]:
        """All matching version receipts overlapping the period. Never guess 'latest'."""
        if (
            type(asset) is not Asset
            or not isinstance(kind, RecordKind)
            or type(period) is not Period
            or not isinstance(metric, str)
            or not metric.strip()
            or (version is not None and (type(version) is not int or version < 1))
            or (provider is not None and (not isinstance(provider, str) or not provider.strip()))
        ):
            raise StorageError("validated query contracts required")
        try:
            rows = self._db.execute(
                "SELECT v.*, c.receipt_id, c.payload FROM versions v JOIN collections c "
                "USING(scope,synthetic,logical_id,version) "
                "WHERE v.scope=? AND v.synthetic=? AND namespace=? AND asset=? "
                "AND kind=? AND metric=? AND period_start<=? AND period_end>=? "
                "AND (? IS NULL OR v.version=?) AND (? IS NULL OR provider=?) "
                "ORDER BY logical_id, v.version, receipt_id",
                (
                    self._scope,
                    self._synthetic,
                    asset.namespace,
                    asset.identifier,
                    kind.value,
                    metric,
                    period.end.isoformat(),
                    period.start.isoformat(),
                    version,
                    version,
                    provider,
                    provider,
                ),
            )
            results = []
            for row in rows:
                observation = _decode(row["payload"])
                economic = _economic(row["payload"])
                logical = _logical(self._scope, self._synthetic, row["record_key"], observation)
                if (
                    row["scope"] != self._scope
                    or row["synthetic"] != self._synthetic
                    or economic != row["economic"]
                    or _digest(economic) != row["content_id"]
                    or logical != row["logical_id"]
                    or _digest(_json([logical, row["payload"]])) != row["receipt_id"]
                    or observation.provenance.source.synthetic != bool(self._synthetic)
                    or observation.provenance.period.start.isoformat() != row["period_start"]
                    or observation.provenance.period.end.isoformat() != row["period_end"]
                    or observation.asset.namespace != row["namespace"]
                    or observation.asset.identifier != row["asset"]
                    or observation.kind.value != row["kind"]
                    or observation.metric != row["metric"]
                    or observation.provenance.source.provider != row["provider"]
                ):
                    raise StorageError("stored data integrity failure")
                results.append(
                    StoredObservation(
                        logical,
                        row["record_key"],
                        row["version"],
                        row["content_id"],
                        row["receipt_id"],
                        observation,
                    )
                )
            return tuple(results)
        except (sqlite3.Error, StorageError, TypeError, ValueError):
            raise StorageError("stored data integrity failure or failed query") from None
