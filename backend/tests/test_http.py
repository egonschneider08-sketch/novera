"""Offline transport tests. All identities, payloads and credentials are synthetic."""

import logging
import traceback
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from threading import Event, Thread

import httpx
import pytest
from novera.http import (
    AccessContext,
    CachePolicy,
    FailureKind,
    FetchError,
    Freshness,
    MemoryCache,
    RetryPolicy,
    SecureHttpClient,
)

CONTEXT = AccessContext("synthetic-user", "basic", "revision-1")
POLICY = RetryPolicy(timeout=2, max_retries=2, backoff_base=1, backoff_cap=10, min_interval=0)


class Clock:
    def __init__(self):
        self.tick = 100.0
        self.start = datetime(2026, 10, 29, tzinfo=timezone.utc)
        self.sleeps = []

    def monotonic(self):
        return self.tick

    def now(self):
        return self.start + timedelta(seconds=self.tick - 100)

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.tick += seconds


@pytest.fixture(autouse=True)
def deny_real_socket_network(monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("real socket network forbidden in HTTP unit tests")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def validate(payload):
    if not isinstance(payload, dict) or type(payload.get("value")) is not int:
        raise ValueError("invalid synthetic response")
    return {"value": payload["value"]}


def build(handler, clock=None, **kwargs):
    clock = clock or Clock()
    policy = kwargs.pop("policy", POLICY)
    client = SecureHttpClient(
        "synthetic-provider",
        "https://provider.invalid",
        policy=policy,
        transport=httpx.MockTransport(handler),
        monotonic=clock.monotonic,
        now=clock.now,
        sleep=clock.sleep,
        jitter=lambda: 0.5,
        **kwargs,
    )
    return client, clock


def get(client, path="/price", **kwargs):
    fields = dict(context=CONTEXT, schema_version="quote-v1", validator=validate)
    return client.get_json(path, **(fields | kwargs))


def test_timeout_extensions_and_connection_reuse_with_fresh_cache():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.extensions["timeout"] == dict(connect=2, read=2, write=2, pool=2)
        return httpx.Response(200, json={"value": 10})

    client, _ = build(handler)
    first = get(client)
    second = get(client)
    assert first.freshness is Freshness.NETWORK
    assert second.freshness is Freshness.FRESH and second.attempts == 0
    assert first.fetched_at == second.fetched_at
    assert len(calls) == 1
    client.close()
    with pytest.raises(RuntimeError):
        get(client)


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
        httpx.ConnectError,
    ],
)
def test_retries_transport_failure_then_succeeds(error):
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) < 3:
            raise error("synthetic sensitive transport text")
        return httpx.Response(200, json={"value": 3})

    client, clock = build(handler)
    assert get(client).attempts == 3
    assert clock.sleeps == [0.5, 1.0]


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_retryable_statuses_have_bounded_attempts(status):
    calls = []
    client, _ = build(lambda r: calls.append(1) or httpx.Response(status))
    with pytest.raises(FetchError) as caught:
        get(client)
    assert len(calls) == 3
    assert caught.value.status == status and caught.value.attempts == 3


@pytest.mark.parametrize("status", [301, 302, 400, 401, 402, 403, 404, 422, 501])
def test_definitive_status_is_not_retried_or_redirected(status):
    calls = []
    client, clock = build(
        lambda r: calls.append(1)
        or httpx.Response(status, headers={"Location": "https://other.invalid"})
    )
    with pytest.raises(FetchError):
        get(client)
    assert len(calls) == 1 and not clock.sleeps


@pytest.mark.parametrize("header,expected", [("7", 7.0), ("0", 0.5), ("invalid", 0.5), ("-5", 0.5)])
def test_retry_after_numeric_zero_and_invalid(header, expected):
    calls = []

    def handler(request):
        calls.append(1)
        return (
            httpx.Response(429, headers={"Retry-After": header})
            if len(calls) == 1
            else httpx.Response(200, json={"value": 1})
        )

    client, clock = build(handler)
    get(client)
    assert clock.sleeps == [expected]


def test_retry_after_http_date_uses_injected_clock_and_is_not_capped_by_backoff():
    clock = Clock()
    header = format_datetime(clock.now() + timedelta(seconds=20), usegmt=True)
    calls = []
    client, _ = build(
        lambda r: calls.append(1)
        or (
            httpx.Response(503, headers={"Retry-After": header})
            if len(calls) == 1
            else httpx.Response(200, json={"value": 1})
        ),
        clock,
    )
    get(client)
    assert clock.sleeps == [20]


def test_long_retry_after_does_not_retry_early_and_cooldown_survives_call():
    calls = []
    client, clock = build(
        lambda r: calls.append(1) or httpx.Response(429, headers={"Retry-After": "120"})
    )
    with pytest.raises(FetchError) as caught:
        get(client)
    assert caught.value.kind is FailureKind.COOLDOWN
    assert len(calls) == 1 and not clock.sleeps
    with pytest.raises(FetchError):
        get(client)
    assert len(calls) == 1


def test_rate_limit_applies_to_distinct_resources_and_contexts():
    calls = []
    client, clock = build(
        lambda r: calls.append(1) or httpx.Response(200, json={"value": 1}),
        policy=replace(POLICY, min_interval=2),
    )
    get(client, "/a")
    get(client, "/b", context=replace(CONTEXT, tenant="second"))
    assert clock.sleeps == [2] and len(calls) == 2


@pytest.mark.parametrize("field", ["tenant", "entitlement", "credential_revision"])
def test_access_context_isolation(field):
    calls = []
    client, _ = build(lambda r: calls.append(1) or httpx.Response(200, json={"value": len(calls)}))
    assert get(client).data == {"value": 1}
    assert get(client, context=replace(CONTEXT, **{field: "other"})).data == {"value": 2}
    assert get(client).data == {"value": 1}


def test_auth_rotation_headers_schema_and_parameters_partition_cache():
    calls = []
    client, _ = build(lambda r: calls.append(1) or httpx.Response(200, json={"value": len(calls)}))
    for kwargs in (
        {"headers": {"Authorization": "Bearer synthetic-one"}},
        {"headers": {"Authorization": "Bearer synthetic-two"}},
        {"schema_version": "v2"},
        {"params": {"symbol": "TEST1"}},
        {"headers": {"Accept-Language": "pt"}},
    ):
        assert get(client, **kwargs).freshness is Freshness.NETWORK
    assert len(calls) == 5


def test_provider_origin_partition_with_shared_cache():
    cache = MemoryCache()
    calls = []

    def transport(request):
        calls.append(1)
        return httpx.Response(200, json={"value": len(calls)})

    first, _ = build(transport, cache=cache)
    second = SecureHttpClient(
        "other-provider",
        "https://provider.invalid",
        cache=cache,
        transport=httpx.MockTransport(transport),
        policy=POLICY,
    )
    third = SecureHttpClient(
        "synthetic-provider",
        "https://other.invalid",
        cache=cache,
        transport=httpx.MockTransport(transport),
        policy=POLICY,
    )
    assert get(first).data["value"] == 1
    assert get(second).data["value"] == 2
    assert get(third).data["value"] == 3


def test_normalized_query_and_header_order_share_cache():
    calls = []
    client, _ = build(lambda r: calls.append(1) or httpx.Response(200, json={"value": 1}))
    get(
        client,
        params={"b": "2", "a": "1"},
        headers={"X-Public": "same", "Accept": "application/json"},
    )
    result = get(
        client,
        params={"a": "1", "b": "2"},
        headers={"accept": "application/json", "x-public": "same"},
    )
    assert result.freshness is Freshness.FRESH and len(calls) == 1


def test_cache_data_is_defensively_copied_and_memory_is_bounded():
    client, _ = build(lambda r: httpx.Response(200, json={"value": 1}), cache=MemoryCache(1))
    result = get(client)
    result.data["value"] = 999
    assert get(client).data["value"] == 1
    get(client, "/other")
    assert get(client).freshness is Freshness.NETWORK


def test_stale_is_explicit_opt_in_with_original_collection_time_and_failure():
    up = [True]
    client, clock = build(
        lambda r: httpx.Response(200, json={"value": 1}) if up[0] else httpx.Response(503)
    )
    policy = CachePolicy(ttl=1, max_stale=10, allow_stale=True)
    first = get(client, cache_policy=policy)
    clock.tick += 2
    up[0] = False
    result = get(client, cache_policy=policy)
    assert result.freshness is Freshness.STALE
    assert result.stale_reason is FailureKind.HTTP_STATUS
    assert result.failure_status == 503 and result.attempts == 3
    assert result.fetched_at == first.fetched_at and result.age_seconds == 3.5


@pytest.mark.parametrize(
    "stale_policy", [CachePolicy(ttl=1), CachePolicy(ttl=1, max_stale=0, allow_stale=True)]
)
def test_stale_not_returned_without_permission_or_beyond_limit(stale_policy):
    up = [True]
    client, clock = build(
        lambda r: httpx.Response(200, json={"value": 1}) if up[0] else httpx.Response(503)
    )
    get(client, cache_policy=stale_policy)
    clock.tick += 2
    up[0] = False
    with pytest.raises(FetchError):
        get(client, cache_policy=stale_policy)


@pytest.mark.parametrize("status", [401, 403, 404])
def test_stale_never_bypasses_auth_or_definitive_failure(status):
    up = [True]
    calls = []
    client, clock = build(
        lambda r: calls.append(1)
        or (httpx.Response(200, json={"value": 1}) if up[0] else httpx.Response(status))
    )
    policy = CachePolicy(ttl=1, max_stale=100, allow_stale=True)
    get(client, cache_policy=policy)
    clock.tick += 2
    up[0] = False
    with pytest.raises(FetchError):
        get(client, cache_policy=policy)
    assert len(calls) == 2
    assert not client._cache._entries


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, text='{"value": NaN}'),
        httpx.Response(200, json={"value": "not an integer"}),
    ],
)
def test_invalid_response_not_retried_or_cached(response):
    calls = []
    client, _ = build(lambda r: calls.append(1) or response)
    with pytest.raises(FetchError) as caught:
        get(client)
    assert caught.value.kind is FailureKind.INVALID_RESPONSE
    assert len(calls) == 1 and not client._cache._entries


def test_oversized_body_is_rejected_and_response_closed():
    response = httpx.Response(200, content=b"x" * 100)
    client, _ = build(lambda r: response, policy=replace(POLICY, max_response_bytes=10))
    with pytest.raises(FetchError):
        get(client)
    assert response.is_closed


def test_failures_are_independent_and_only_valid_resources_are_cached():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return (
            httpx.Response(503)
            if request.url.path == "/bad"
            else httpx.Response(200, json={"value": 1})
        )

    client, _ = build(handler)
    first = get(client, "/good")
    with pytest.raises(FetchError):
        get(client, "/bad")
    assert get(client, "/later").data == first.data
    assert get(client, "/good").freshness is Freshness.FRESH
    assert calls == ["/good", "/bad", "/bad", "/bad", "/later"]


def test_no_credentials_in_keys_logs_errors_or_envelope_repr(caplog):
    sensitive = "synthetic-private-marker"

    def handler(request):
        logging.getLogger("httpcore.http11").warning("headers=%s", sensitive)
        raise httpx.ReadTimeout(sensitive + str(request.url))

    client, _ = build(handler)
    with caplog.at_level(logging.DEBUG), pytest.raises(FetchError) as caught:
        get(client, headers={"Authorization": "Bearer " + sensitive})
    formatted = "".join(traceback.format_exception(caught.value))
    assert sensitive not in caplog.text + formatted + repr(client._cache._entries)
    assert str(caught.value).startswith("HTTP fetch failed: timeout")
    logging.getLogger("httpcore.http11").warning("unrelated traffic still visible")
    assert "unrelated traffic" in caplog.text


def test_hmac_key_does_not_contain_or_equal_unkeyed_secret_hash():
    client, _ = build(lambda r: httpx.Response(200, json={"value": 1}))
    get(client, headers={"Authorization": "Bearer synthetic-marker"})
    keys = list(client._cache._entries)
    assert len(keys) == 1 and len(keys[0]) == 64
    assert "synthetic" not in keys[0]


@pytest.mark.parametrize(
    "origin",
    [
        "http://provider.invalid",
        "https://user:password@provider.invalid",  # pragma: allowlist secret -- synthetic invalid origin
        "https://provider.invalid/path",
        "https://provider.invalid?token=x",
    ],
)
def test_origin_rejects_credentials_insecure_scheme_or_dynamic_path(origin):
    with pytest.raises(ValueError):
        SecureHttpClient("test", origin)


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "params": {"api_key": "synthetic"}  # pragma: allowlist secret -- synthetic fixture
        },
        {"headers": {"Cookie": "session=synthetic"}},
        {"headers": {"Host": "other.invalid"}},
    ],
)
def test_request_rejects_query_credentials_cookies_and_routing_overrides(kwargs):
    client, _ = build(lambda r: pytest.fail("no request expected"))
    with pytest.raises(ValueError):
        get(client, **kwargs)


@pytest.mark.parametrize(
    "path", ["https://other.invalid", "//other.invalid", "/x?token=synthetic", "/x#fragment"]
)
def test_absolute_urls_query_and_fragment_rejected(path):
    client, _ = build(lambda r: pytest.fail("no request expected"))
    with pytest.raises(ValueError):
        get(client, path)


def test_cookies_received_are_never_reused_between_contexts():
    def handler(request):
        assert "cookie" not in request.headers
        return httpx.Response(200, headers={"Set-Cookie": "session=synthetic"}, json={"value": 1})

    client, _ = build(handler)
    get(client)
    get(client, context=replace(CONTEXT, tenant="other"))


def test_concurrent_network_calls_are_serialized_per_provider():
    entered, release = Event(), Event()
    active = []

    def handler(request):
        active.append(request.url.path)
        if request.url.path == "/first":
            entered.set()
            assert release.wait(5)
        return httpx.Response(200, json={"value": 1})

    client, _ = build(handler)
    results = []
    first = Thread(target=lambda: results.append(get(client, "/first")))
    second = Thread(target=lambda: results.append(get(client, "/second")))
    first.start()
    assert entered.wait(5)
    second.start()
    assert active == ["/first"]
    release.set()
    first.join(5)
    second.join(5)
    assert len(results) == 2 and active == ["/first", "/second"]


@pytest.mark.parametrize(
    "directive", ["no-store", "no-cache", "must-revalidate", "max-age=0", "max-age=invalid"]
)
def test_provider_cache_directives_can_forbid_storage(directive):
    client, _ = build(
        lambda r: httpx.Response(200, headers={"Cache-Control": directive}, json={"value": 1})
    )
    get(client)
    assert get(client).freshness is Freshness.NETWORK
    assert not client._cache._entries


def test_provider_max_age_and_age_shorten_local_freshness():
    client, clock = build(
        lambda r: httpx.Response(
            200, headers={"Cache-Control": "max-age=10", "Age": "8"}, json={"value": 1}
        )
    )
    get(client)
    clock.tick += 1
    assert get(client).freshness is Freshness.FRESH
    clock.tick += 1
    assert get(client).freshness is Freshness.NETWORK


@pytest.mark.parametrize(
    "payload", [{"access_token": "synthetic-other"}, {"echo": "synthetic-private"}]
)
def test_credentials_in_response_rejected_before_validation_or_cache(payload):
    client, _ = build(lambda r: httpx.Response(200, json=payload))
    with pytest.raises(FetchError) as caught:
        get(
            client,
            headers={"Authorization": "Bearer synthetic-private"},
            validator=lambda value: value,
        )
    assert caught.value.kind is FailureKind.INVALID_RESPONSE
    assert not client._cache._entries


def test_credential_in_an_unexpected_query_field_is_rejected():
    client, _ = build(lambda r: pytest.fail("should not transmit"))
    with pytest.raises(ValueError):
        get(
            client,
            params={"symbol": "synthetic-private"},
            headers={"Authorization": "Bearer synthetic-private"},
        )


def test_cache_can_be_invalidated_on_access_revocation():
    client, _ = build(lambda r: httpx.Response(200, json={"value": 1}))
    get(client)
    client._cache.clear()
    assert get(client).freshness is Freshness.NETWORK


def test_disabled_cache_neither_reads_nor_writes_entries():
    calls = []
    client, _ = build(lambda r: calls.append(1) or httpx.Response(200, json={"value": len(calls)}))
    get(client)
    assert get(client, cache_policy=CachePolicy(enabled=False)).data["value"] == 2
    assert get(client).data["value"] == 1


def test_stricter_ttl_is_respected_and_later_policy_cannot_extend_original_entry():
    client, clock = build(lambda r: httpx.Response(200, json={"value": 1}))
    get(client, cache_policy=CachePolicy(ttl=2))
    clock.tick += 2
    assert get(client, cache_policy=CachePolicy(ttl=100)).freshness is Freshness.NETWORK
    clock.tick += 1
    assert get(client, cache_policy=CachePolicy(ttl=1)).freshness is Freshness.NETWORK


def test_clock_regression_does_not_resurrect_cache():
    client, clock = build(lambda r: httpx.Response(200, json={"value": 1}))
    get(client)
    clock.tick -= 10
    assert get(client).freshness is Freshness.NETWORK


def test_validator_exception_does_not_leak_payload(caplog):
    def reject(payload):
        raise ValueError("synthetic-sensitive-body")

    client, _ = build(lambda r: httpx.Response(200, json={"value": 1}))
    with pytest.raises(FetchError) as caught:
        get(client, validator=reject)
    assert (
        "synthetic-sensitive-body"
        not in "".join(traceback.format_exception(caught.value)) + caplog.text
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"timeout": 0},
        {"timeout": float("nan")},
        {"max_retries": -1},
        {"max_retries": True},
        {"max_retries": 9},
        {"max_wait": 0},
        {"min_interval": -1},
        {"max_response_bytes": 0},
    ],
)
def test_invalid_retry_policies_fail_before_network(changes):
    with pytest.raises(ValueError):
        replace(POLICY, **changes)


@pytest.mark.parametrize("changes", [{"ttl": -1}, {"ttl": float("inf")}, {"allow_stale": "true"}])
def test_invalid_cache_policy(changes):
    with pytest.raises(ValueError):
        CachePolicy(**changes)


def test_no_write_method_can_be_implicitly_retried():
    client, _ = build(lambda r: pytest.fail("no network"))
    assert not hasattr(client, "post")
    assert not hasattr(client, "request")


def test_none_is_a_valid_validated_payload_not_a_transport_failure():
    client, _ = build(lambda r: httpx.Response(200, json={"value": 1}))
    assert get(client, validator=lambda value: None).data is None


def test_response_is_closed_on_retry_status_and_validator_failure():
    responses = []

    def handler(request):
        response = httpx.Response(503)
        responses.append(response)
        return response

    client, _ = build(handler)
    with pytest.raises(FetchError):
        get(client)
    assert all(response.is_closed for response in responses)


def test_unknown_headers_are_also_part_of_cache_identity():
    calls = []
    client, _ = build(lambda r: calls.append(1) or httpx.Response(200, json={"value": len(calls)}))
    assert get(client, headers={"X-Custom-Context": "a"}).data["value"] == 1
    assert get(client, headers={"X-Custom-Context": "b"}).data["value"] == 2


def test_decimal_json_values_preserve_financial_precision():
    from decimal import Decimal

    client, _ = build(
        lambda r: httpx.Response(200, content=b'{"amount":0.12345678901234567890123456789}')
    )
    result = get(client, validator=lambda payload: payload["amount"])
    assert result.data == Decimal("0.12345678901234567890123456789")


def test_duplicate_json_fields_are_not_silently_overwritten():
    client, _ = build(lambda r: httpx.Response(200, content=b'{"value":1,"value":2}'))
    with pytest.raises(FetchError) as caught:
        get(client)
    assert caught.value.kind is FailureKind.INVALID_RESPONSE


def test_partial_body_failure_is_not_cached_and_can_recover():
    class BrokenStream(httpx.SyncByteStream):
        closed = False

        def __iter__(self):
            yield b'{"value":'
            raise httpx.ReadTimeout("synthetic partial response")

        def close(self):
            self.closed = True

    broken = BrokenStream()
    calls = []

    def handler(request):
        calls.append(1)
        return (
            httpx.Response(200, stream=broken)
            if len(calls) == 1
            else httpx.Response(200, json={"value": 2})
        )

    client, _ = build(handler)
    assert get(client).data == {"value": 2}
    assert broken.closed
    assert get(client).freshness is Freshness.FRESH
    assert len(calls) == 2


def test_stale_opt_in_does_not_cross_entitlement_on_failure():
    up = [True]
    client, clock = build(
        lambda r: httpx.Response(200, json={"value": 1}) if up[0] else httpx.Response(503)
    )
    policy = CachePolicy(ttl=1, max_stale=100, allow_stale=True)
    get(client, cache_policy=policy)
    clock.tick += 2
    up[0] = False
    with pytest.raises(FetchError):
        get(client, cache_policy=policy, context=replace(CONTEXT, entitlement="other"))
    assert get(client, cache_policy=policy).freshness is Freshness.STALE


def test_default_transport_logs_are_scoped_to_active_thread(caplog):
    started, release = Event(), Event()

    def handler(request):
        started.set()
        assert release.wait(5)
        return httpx.Response(200, json={"value": 1})

    client, _ = build(handler)
    thread = Thread(target=lambda: get(client))
    with caplog.at_level(logging.WARNING):
        thread.start()
        assert started.wait(5)
        logging.getLogger("httpcore.http11").warning("outside worker is visible")
        release.set()
        thread.join(5)
    assert "outside worker" in caplog.text


def test_auth_failure_invalidates_other_resources_in_same_partition_only():
    def handler(request):
        return (
            httpx.Response(403)
            if request.url.path == "/forbidden"
            else httpx.Response(200, json={"value": 1})
        )

    client, _ = build(handler)
    get(client, "/good")
    other = replace(CONTEXT, tenant="different-user")
    get(client, "/good", context=other)
    with pytest.raises(FetchError):
        get(client, "/forbidden")
    assert get(client, "/good", context=other).freshness is Freshness.FRESH
    assert get(client, "/good").freshness is Freshness.NETWORK


def test_vary_star_prevents_storage():
    client, _ = build(lambda r: httpx.Response(200, json={"value": 1}, headers={"Vary": "*"}))
    get(client)
    assert not client._cache._entries


def test_import_module_has_no_socket_network(tmp_path):
    import subprocess
    import sys

    code = (
        "import socket; "
        "deny=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network forbidden')); "
        "socket.getaddrinfo=deny; socket.create_connection=deny; socket.socket.connect=deny; import novera.http; print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert result.stdout.strip() == "ok"


def test_auth_invalidation_partition_is_independent_of_header_order():
    def handler(request):
        return (
            httpx.Response(403)
            if request.url.path == "/forbidden"
            else httpx.Response(200, json={"value": 1})
        )

    client, _ = build(handler)
    first = {"Authorization": "Bearer synthetic-one", "X-API-Key": "synthetic-two"}
    reordered = dict(reversed(list(first.items())))
    get(client, "/good", headers=first)
    with pytest.raises(FetchError):
        get(client, "/forbidden", headers=reordered)
    assert get(client, "/good", headers=first).freshness is Freshness.NETWORK


def test_proxy_authorization_cannot_be_sent_to_origin():
    client, _ = build(lambda r: pytest.fail("must not transmit proxy credential"))
    with pytest.raises(ValueError):
        get(client, headers={"Proxy-Authorization": "Bearer synthetic-proxy"})
