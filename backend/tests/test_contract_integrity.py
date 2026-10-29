"""Additional contract invariants; deliberately no invented provider implementation."""

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest
from novera.contracts import Asset, Observation, Period, Provenance, Quality, RecordKind, Source


def record(quality=Quality.PRESENT, value=Decimal("0"), reason=None):
    return Observation(
        Asset("synthetic", "test-asset"),
        RecordKind.INDICATOR,
        "test_ratio",
        value,
        quality,
        "ratio",
        None,
        Provenance(
            Source("test", "fixture:integrity", "1", True),
            Period(date(2025, 1, 1), date(2025, 12, 31)),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        reason,
    )


def test_constructor_does_not_call_external_transport(monkeypatch):
    # Only a guard for these Python entry points; not universal I/O isolation.
    import socket

    transport = Mock(side_effect=AssertionError("unexpected external call"))
    monkeypatch.setattr(socket, "socket", transport)
    monkeypatch.setattr(socket, "getaddrinfo", transport)
    assert record().value == Decimal("0")
    transport.assert_not_called()


@pytest.mark.parametrize("quality", [Quality.MISSING, Quality.INVALID, Quality.NOT_APPLICABLE])
def test_absence_cannot_be_replaced_with_zero_without_explicit_reclassification(quality):
    item = record(quality, None, "not evaluable")
    with pytest.raises(ValueError):
        replace(item, value=Decimal("0"))
    corrected = replace(item, value=Decimal("0"), quality=Quality.PRESENT, reason=None)
    assert corrected.quality is Quality.PRESENT
    assert item.quality is quality


def test_immutable_record_and_nested_provenance():
    item = record()
    with pytest.raises(FrozenInstanceError):
        item.value = Decimal("999")
    with pytest.raises(FrozenInstanceError):
        item.provenance.source.provider = "other"


def test_equivalent_offsets_compare_as_instants():
    provenance = record().provenance
    local_time = datetime(2026, 1, 1, 21, tzinfo=timezone(timedelta(hours=-3)))
    result = replace(
        provenance, collected_at=local_time, published_at=datetime(2026, 1, 2, tzinfo=timezone.utc)
    )
    assert result.published_at == result.collected_at
    with pytest.raises(ValueError):
        replace(result, published_at=result.published_at + timedelta(microseconds=1))


def test_unknown_publication_preserves_collection_without_inventing_as_of_date():
    item = record()
    provenance = replace(
        item.provenance, published_at=None, publication_unknown_reason="not supplied"
    )
    assert provenance.collected_at == item.provenance.collected_at
    assert provenance.published_at is None


def test_distinct_assets_and_revisions_remain_distinct():
    original = record()
    renamed = replace(original, asset=Asset("synthetic", "other-asset"))
    revised = replace(
        original,
        provenance=replace(
            original.provenance, source=replace(original.provenance.source, rule_version="2")
        ),
    )
    assert len({original, renamed, revised}) == 3
