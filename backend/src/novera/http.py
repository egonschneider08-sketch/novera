"""GET-only JSON transport with bounded retries, scoped cache and explicit freshness."""

import hashlib
import hmac
import json
import logging
import math
import random
import secrets
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from enum import StrEnum
from threading import Lock
from typing import Generic, TypeVar

import httpx

T = TypeVar("T")
_transport_active = ContextVar("novera_http_transport_active", default=False)


class _TransportLogGuard(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Raw transport records can contain response headers/cookies or URLs.
        return not _transport_active.get()


for _logger_name in (
    "httpx",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
):
    logging.getLogger(_logger_name).addFilter(_TransportLogGuard())


class FailureKind(StrEnum):
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    HTTP_STATUS = "http_status"
    RATE_LIMITED = "rate_limited"
    INVALID_RESPONSE = "invalid_response"
    COOLDOWN = "cooldown"


class FetchError(RuntimeError):
    """Safe error metadata only: no request, URL, credentials or response body."""

    def __init__(self, kind: FailureKind, attempts: int, status: int | None = None):
        self.kind, self.attempts, self.status = kind, attempts, status
        super().__init__(f"HTTP fetch failed: {kind.value}; attempts={attempts}; status={status}")


class Freshness(StrEnum):
    NETWORK = "network"
    FRESH = "fresh"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class AccessContext:
    # Opaque non-secret IDs. Credential material belongs only in request headers.
    tenant: str = field(repr=False)
    entitlement: str = field(repr=False)
    credential_revision: str = field(repr=False)

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.tenant, self.entitlement, self.credential_revision)
        ):
            raise ValueError("access context requires non-empty opaque identifiers")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    timeout: float = 10.0
    max_retries: int = 2
    backoff_base: float = 0.5
    backoff_cap: float = 8.0
    max_wait: float = 60.0
    min_interval: float = 0.2
    max_response_bytes: int = 2_000_000

    def __post_init__(self) -> None:
        for name in ("timeout", "backoff_base", "backoff_cap", "max_wait", "min_interval"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError("invalid nonnegative HTTP policy duration")
        if self.timeout == 0 or self.max_wait == 0:
            raise ValueError("timeout and max_wait must be positive")
        if type(self.max_retries) is not int or not 0 <= self.max_retries <= 8:
            raise ValueError("max_retries must be an integer in [0, 8]")
        if type(self.max_response_bytes) is not int or self.max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be a positive integer")


@dataclass(frozen=True, slots=True)
class CachePolicy:
    ttl: float = 60.0
    max_stale: float = 0.0
    allow_stale: bool = False
    enabled: bool = True

    def __post_init__(self) -> None:
        for value in (self.ttl, self.max_stale):
            if (
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError("cache durations must be finite and nonnegative")
        if type(self.allow_stale) is not bool or type(self.enabled) is not bool:
            raise ValueError("cache flags must be bool")


@dataclass(frozen=True, slots=True)
class JsonEnvelope(Generic[T]):
    data: T = field(repr=False)
    freshness: Freshness
    fetched_at: datetime
    age_seconds: float
    attempts: int
    stale_reason: FailureKind | None = None
    failure_status: int | None = None


@dataclass(frozen=True, slots=True)
class _Entry:
    data: object = field(repr=False)
    fetched_at: datetime
    monotonic_at: float
    ttl: float
    partition: str


@dataclass(frozen=True, slots=True)
class _Outcome(Generic[T]):
    data: T | None = field(default=None, repr=False)
    failure: FailureKind | None = None
    status: int | None = None
    retry_after: float | None = None
    cache_ttl: float | None = None


def _cache_ttl(headers: httpx.Headers) -> float | None:
    if "*" in headers.get("Vary", "").split(","):
        return None
    directives = [part.strip().lower() for part in headers.get("Cache-Control", "").split(",")]
    if any(
        part.split("=", 1)[0] in ("no-store", "no-cache", "must-revalidate") for part in directives
    ):
        return None  # Conservative: these responses are not stored, including stale fallback.
    lifetime = math.inf
    for part in directives:
        if part.startswith("max-age="):
            raw = part.split("=", 1)[1].strip('"')
            if not raw.isascii() or not raw.isdecimal():
                return None
            lifetime = min(lifetime, float(raw))
    age = headers.get("Age", "0")
    if not age.isascii() or not age.isdecimal():
        return None
    remaining = lifetime - float(age)
    return remaining if remaining > 0 else None


def _credential_values(headers: httpx.Headers) -> tuple[str, ...]:
    values = []
    for name, value in headers.multi_items():
        normalized = name.replace("-", "").replace("_", "").casefold()
        if any(
            word in normalized
            for word in ("authorization", "apikey", "token", "secret", "credential")
        ):
            values.append(value)
            if " " in value:
                values.append(value.split(" ", 1)[1])
    return tuple(value for value in values if value)


def _contains_credentials(payload: object, credentials: tuple[str, ...]) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = str(key).replace("_", "").replace("-", "").casefold()
            if normalized in (
                "token",
                "accesstoken",
                "refreshtoken",
                "apikey",
                "password",
                "secret",
                "authorization",
            ):
                return True
            if _contains_credentials(value, credentials):
                return True
    elif isinstance(payload, list):
        return any(_contains_credentials(item, credentials) for item in payload)
    elif isinstance(payload, str):
        return any(value in payload for value in credentials)
    return False


class MemoryCache:
    """Bounded, process-local validated payloads; only HMAC digests as keys."""

    def __init__(self, max_entries: int = 256):
        if type(max_entries) is not int or max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._secret = secrets.token_bytes(32)
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = Lock()
        self._max_entries = max_entries

    def clear(self) -> None:
        """Explicit invalidation for access changes; does not bypass provider cooldown."""
        with self._lock:
            self._entries.clear()

    def _key(self, identity: tuple) -> str:
        raw = json.dumps(identity, separators=(",", ":"), ensure_ascii=True).encode()
        return hmac.new(self._secret, raw, hashlib.sha256).hexdigest()

    def _get(self, key: str) -> _Entry | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
                return deepcopy(entry)
            return None

    def _put(self, key: str, entry: _Entry) -> None:
        with self._lock:
            self._entries[key] = deepcopy(entry)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def _drop_partition(self, partition: str) -> None:
        with self._lock:
            for key in [
                key for key, entry in self._entries.items() if entry.partition == partition
            ]:
                del self._entries[key]

    def _drop(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)


_RETRY_STATUSES = frozenset((408, 429, 500, 502, 503, 504))
_SENSITIVE_QUERY_NAMES = frozenset(
    (
        "token",
        "access_token",
        "api_key",
        "apikey",
        "key",
        "password",
        "secret",
        "authorization",
        "signature",
        "credential",
    )
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _retry_after(raw: str | None, now: datetime) -> float | None:
    if raw is None:
        return None
    raw = raw.strip()
    try:
        if raw.isascii() and raw.isdecimal():
            result = float(raw)
            return result if math.isfinite(result) else math.inf
        timestamp = parsedate_to_datetime(raw)
        if timestamp.utcoffset() is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return max(0.0, (timestamp - now).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("nonfinite JSON number")


class SecureHttpClient:
    """One reusable synchronous client per trusted provider origin.

    Serializes network calls/retries per instance. Share the instance to enforce
    provider-wide spacing; no cross-process/distributed quota coordination.
    """

    def __init__(
        self,
        provider: str,
        origin: str,
        *,
        policy: RetryPolicy = RetryPolicy(),
        cache: MemoryCache | None = None,
        transport: httpx.BaseTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = _utcnow,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ):
        try:
            url = httpx.URL(origin)
            valid = (
                url.scheme == "https"
                and url.host
                and not url.userinfo
                and not url.query
                and not url.fragment
                and url.path == "/"
            )
        except (httpx.InvalidURL, TypeError):
            valid = False
        if not valid or not isinstance(provider, str) or not provider.strip():
            raise ValueError("trusted HTTPS provider origin required, without credentials or path")
        if not isinstance(policy, RetryPolicy):
            raise ValueError("RetryPolicy required")
        self._provider, self._origin = provider, url
        self._policy = policy
        self._cache = cache if cache is not None else MemoryCache()
        # Direct transport avoids Client cookie jars, ambient proxies and implicit retries.
        self._transport = (
            transport if transport is not None else httpx.HTTPTransport(retries=0, trust_env=False)
        )
        self._monotonic, self._now, self._sleep, self._jitter = monotonic, now, sleep, jitter
        self._gate = Lock()
        self._next_start = 0.0
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        with self._gate:
            if not self._closed:
                self._transport.close()
                self._closed = True

    def _request(
        self, path: str, params: Mapping[str, str] | None, headers: Mapping[str, str] | None
    ) -> httpx.Request:
        try:
            if (
                not isinstance(path, str)
                or not path.startswith("/")
                or path.startswith("//")
                or any(c in path for c in ("?", "#", "\\"))
            ):
                raise ValueError("invalid endpoint")
            pairs = sorted((params or {}).items())
            if any(
                not isinstance(k, str)
                or not isinstance(v, str)
                or k.casefold().replace("-", "_") in _SENSITIVE_QUERY_NAMES
                for k, v in pairs
            ):
                raise ValueError("credentials must not be in query parameters")
            request_headers = httpx.Headers({"Accept": "application/json"})
            request_headers.update(headers or {})
            if any(
                name in request_headers
                for name in ("cookie", "host", "content-length", "transfer-encoding")
            ):
                raise ValueError("cookies and routing headers unsupported")
            if any("\r" in value or "\n" in value for value in request_headers.values()):
                raise ValueError("invalid header value")
            request = httpx.Request(
                "GET",
                self._origin.copy_with(path=path),
                params=pairs,
                headers=request_headers,
                extensions={"timeout": httpx.Timeout(self._policy.timeout).as_dict()},
            )
            if any(value in str(request.url) for value in _credential_values(request_headers)):
                raise ValueError("credential found in URL")
            return request
        except (ValueError, TypeError, UnicodeError, httpx.InvalidURL):
            raise ValueError(
                "invalid HTTP request; use public parameters and header credentials"
            ) from None

    def _wait_slot(self, attempts: int) -> None:
        delay = self._next_start - self._monotonic()
        if delay > self._policy.max_wait:
            raise FetchError(FailureKind.COOLDOWN, attempts)
        if delay > 0:
            self._sleep(delay)
        self._next_start = self._monotonic() + self._policy.min_interval

    def _send(self, request: httpx.Request, validator: Callable[[object], T]) -> _Outcome[T]:
        token = _transport_active.set(True)
        try:
            try:
                response = self._transport.handle_request(request)
                try:
                    status = response.status_code
                    retry = _retry_after(response.headers.get("Retry-After"), self._now())
                    if status != 200:
                        kind = (
                            FailureKind.RATE_LIMITED if status == 429 else FailureKind.HTTP_STATUS
                        )
                        return _Outcome(failure=kind, status=status, retry_after=retry)
                    chunks = bytearray()
                    for chunk in response.iter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > self._policy.max_response_bytes:
                            return _Outcome(failure=FailureKind.INVALID_RESPONSE, status=status)
                    try:
                        payload = json.loads(
                            bytes(chunks),
                            parse_constant=_reject_constant,
                            parse_float=Decimal,
                            object_pairs_hook=_unique_object,
                        )
                        if _contains_credentials(payload, _credential_values(request.headers)):
                            return _Outcome(failure=FailureKind.INVALID_RESPONSE, status=status)
                        validated = deepcopy(validator(payload))
                    except Exception:
                        # Validators are trusted, but their exception text may contain payload secrets.
                        return _Outcome(failure=FailureKind.INVALID_RESPONSE, status=status)
                    return _Outcome(
                        data=validated, status=status, cache_ttl=_cache_ttl(response.headers)
                    )
                finally:
                    response.close()
            except httpx.TimeoutException:
                return _Outcome(failure=FailureKind.TIMEOUT)
            except httpx.LocalProtocolError:
                return _Outcome(failure=FailureKind.INVALID_RESPONSE)
            except httpx.TransportError:
                return _Outcome(failure=FailureKind.TRANSPORT)
            except httpx.DecodingError:
                return _Outcome(failure=FailureKind.INVALID_RESPONSE)
        finally:
            _transport_active.reset(token)

    def get_json(
        self,
        path: str,
        *,
        context: AccessContext,
        schema_version: str,
        validator: Callable[[object], T],
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        cache_policy: CachePolicy = CachePolicy(),
    ) -> JsonEnvelope[T]:
        if (
            not isinstance(context, AccessContext)
            or not isinstance(cache_policy, CachePolicy)
            or not isinstance(schema_version, str)
            or not schema_version.strip()
            or not callable(validator)
        ):
            raise ValueError("validated access context, schema version and validator required")
        request = self._request(path, params, headers)
        key = self._cache._key(
            (
                self._provider,
                context.tenant,
                context.entitlement,
                context.credential_revision,
                schema_version,
                request.method,
                str(request.url),
                sorted(request.headers.multi_items()),
            )
        )
        partition = self._cache._key(
            (
                self._provider,
                str(self._origin),
                context.tenant,
                context.entitlement,
                context.credential_revision,
                _credential_values(request.headers),
            )
        )
        with self._gate:
            if self._closed:
                raise RuntimeError("HTTP client is closed")
            entry = self._cache._get(key) if cache_policy.enabled else None
            if entry is not None and self._monotonic() < entry.monotonic_at:
                self._cache._drop(key)
                entry = None
            if entry is not None:
                age = self._monotonic() - entry.monotonic_at
                if age < min(entry.ttl, cache_policy.ttl):
                    return JsonEnvelope(
                        deepcopy(entry.data), Freshness.FRESH, entry.fetched_at, age, 0
                    )
            attempts = 0
            failure = FailureKind.TRANSPORT
            status = None
            for attempt in range(self._policy.max_retries + 1):
                try:
                    self._wait_slot(attempts)
                except FetchError:
                    failure = FailureKind.COOLDOWN
                    break
                attempts += 1
                outcome = self._send(request, validator)
                data, failure, status, retry_after = (
                    outcome.data,
                    outcome.failure,
                    outcome.status,
                    outcome.retry_after,
                )
                if failure is None:
                    fetched_at = self._now()
                    if cache_policy.enabled and outcome.cache_ttl is not None:
                        self._cache._put(
                            key,
                            _Entry(
                                data,
                                fetched_at,
                                self._monotonic(),
                                min(cache_policy.ttl, outcome.cache_ttl),
                                partition,
                            ),
                        )
                    if outcome.cache_ttl is None:
                        self._cache._drop(key)
                    return JsonEnvelope(
                        deepcopy(data), Freshness.NETWORK, fetched_at, 0.0, attempts
                    )
                transient = (
                    failure in (FailureKind.TIMEOUT, FailureKind.TRANSPORT)
                    or status in _RETRY_STATUSES
                )
                if not transient:
                    # Never reuse a previously cached entitlement after an auth/validation failure.
                    if status in (401, 403):
                        self._cache._drop_partition(partition)
                    else:
                        self._cache._drop(key)
                    raise FetchError(failure, attempts, status) from None
                if retry_after is not None and status in _RETRY_STATUSES:
                    self._next_start = max(self._next_start, self._monotonic() + retry_after)
                if attempt == self._policy.max_retries:
                    break
                sample = self._jitter()
                if not 0 <= sample <= 1 or not math.isfinite(sample):
                    raise ValueError("jitter must return a finite sample in [0, 1]")
                backoff = (
                    min(self._policy.backoff_cap, self._policy.backoff_base * (2**attempt)) * sample
                )
                self._next_start = max(self._next_start, self._monotonic() + backoff)
            if entry is not None and cache_policy.allow_stale and self._cache._get(key) is not None:
                age = self._monotonic() - entry.monotonic_at
                if 0 <= age <= min(entry.ttl, cache_policy.ttl) + cache_policy.max_stale:
                    return JsonEnvelope(
                        deepcopy(entry.data),
                        Freshness.STALE,
                        entry.fetched_at,
                        age,
                        attempts,
                        failure,
                        status,
                    )
            raise FetchError(failure, attempts, status) from None
