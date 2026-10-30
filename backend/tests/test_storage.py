"""Local SQLite storage tests; all values are synthetic and no network is used."""
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from novera.contracts import Asset, Observation, Period, Provenance, Quality, RecordKind, Source
from novera.storage import ObservationStore, StorageScope, StorageError

NOW = datetime(2026,10,29,18,30,tzinfo=timezone.utc)
DAY = date(2026,10,28)
SCOPE = StorageScope('synthetic-tenant','plan','v1')


def observation(*, value=Decimal('0.12345678901234567890'), quality=Quality.PRESENT, kind=RecordKind.INDICATOR, synthetic=True, collected_at=NOW, source_reference='https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados?dataInicial=28%2F10%2F2026&dataFinal=28%2F10%2F2026&formato=json'):
    return Observation(asset=Asset('bcb.sgs','432'),kind=kind,metric='ratio',value=value,quality=quality,unit='fraction/year',currency=None,
        provenance=Provenance(Source('bcb',source_reference,'v1',synthetic),Period(DAY,DAY),collected_at,None,'publication_unknown'))

@pytest.fixture
def store():
    with ObservationStore.memory(scope=SCOPE,synthetic=True) as db: yield db

@pytest.fixture
def dbfile(tmp_path):
    return tmp_path/'observations.sqlite3'

def read(db, sample=None, **kwargs):
    sample=sample or observation()
    return db.query(asset=sample.asset,kind=sample.kind,metric=sample.metric,period=sample.provenance.period,**kwargs)


def test_roundtrip_no_float_provenance_and_exact_zero(store):
    sample=observation()
    r=store.ingest('event-1',sample)
    assert r.observation==sample and read(store)==(r,)
    assert r.observation.value==Decimal('0.12345678901234567890')
    zero=replace(sample,value=Decimal('0'))
    z=store.ingest('event-2',zero)
    assert z.version==1 and len(read(store))==2

@pytest.mark.parametrize('q', [Quality.MISSING,Quality.INVALID,Quality.NOT_APPLICABLE])
def test_missing_invalid_not_applicable_are_not_zero(store,q):
    obj=replace(observation(),value=None,quality=q,reason='synthetic_missing')
    r=store.ingest('event',obj)
    assert read(store,obj)==(r,)


def test_same_data_is_idempotent_and_revisions_preserve_history(store):
    v=observation()
    first=store.ingest('event-1',v)
    assert store.ingest('event-1',v)==first
    assert len(read(store))==1
    corrected=store.ingest('event-1',replace(v,value=Decimal('43')))
    assert corrected.version==2
    assert len(read(store))==2
    assert store.ingest('event-1',v).version==1
    assert len(read(store))==2
    assert read(store,version=1)==(first,)
    assert read(store,version=2)==(corrected,)


def test_new_collection_of_same_economics_adds_receipt_not_version(store):
    v=observation()
    a=store.ingest('event-1',v)
    b=store.ingest('event-1',replace(v,provenance=replace(v.provenance,collected_at=NOW+timedelta(minutes=3))))
    assert a.version==b.version==1
    assert a.receipt_id!=b.receipt_id
    assert len(read(store))==2


def test_atomic_batch_rollbacks_after_first_insert(store):
    with pytest.raises(StorageError,match='rolled back'):
        store.ingest_many([('ok',observation()),('bad',replace(observation(),provenance=replace(observation().provenance,source=replace(observation().provenance.source,synthetic=False))))])
    assert read(store)==()


def test_segregation_across_tenants_and_synthetic(dbfile):
    with ObservationStore.local(dbfile,scope=SCOPE,synthetic=True,create=True) as first:
        first.ingest('abc',observation())
    with ObservationStore.local(dbfile,scope=replace(SCOPE,tenant='other'),synthetic=True) as other:
        assert read(other)==()
        other.ingest('abc',observation())
    with ObservationStore.local(dbfile,scope=SCOPE,synthetic=False) as real:
        assert read(real)==()
        real.ingest('abc',observation(synthetic=False))
    with ObservationStore.local(dbfile,scope=SCOPE,synthetic=True) as original:
        assert len(read(original))==1


def test_reopen_and_parametrized_queries(dbfile):
    with ObservationStore.local(dbfile,scope=SCOPE,synthetic=True,create=True) as first:
        r=first.ingest('one',observation())
    with ObservationStore.local(dbfile,scope=SCOPE,synthetic=True) as reopened:
        assert read(reopened)==(r,)
        assert reopened.ingest('one',observation())==r
        assert read(reopened,provider="fixture' OR 1=1 --")==()
        assert read(reopened,version=99)==()
        assert reopened.query(asset=observation().asset,kind=RecordKind.INDICATOR,metric='ratio',period=Period(date(2000,1,1),date(2000,1,2)))==()

@pytest.mark.parametrize('sql',["PRAGMA user_version=999","CREATE TABLE surprise(x)"])
def test_unknown_schema_is_rejected_without_migration(dbfile,sql):
    with ObservationStore.local(dbfile,scope=SCOPE,synthetic=True,create=True): pass
    with sqlite3.connect(dbfile) as db: db.execute(sql)
    with pytest.raises(StorageError,match='schema'):
        ObservationStore.local(dbfile,scope=SCOPE,synthetic=True)


def test_no_implicit_creation_and_no_overwrite(dbfile):
    with pytest.raises(sqlite3.OperationalError):
        ObservationStore.local(dbfile,scope=SCOPE,synthetic=True)
    assert not dbfile.exists()
    dbfile.write_bytes(b'hello')
    with pytest.raises(FileExistsError):
        ObservationStore.local(dbfile,scope=SCOPE,synthetic=True,create=True)
    assert dbfile.read_bytes()==b'hello'
    with pytest.raises(StorageError,match='absolute'):
        ObservationStore.local('relative.sqlite3',scope=SCOPE,synthetic=True,create=True)


def test_tampering_fails_closed(dbfile):
    with ObservationStore.local(dbfile,scope=SCOPE,synthetic=True,create=True) as store:
        store.ingest('one',observation())
        with sqlite3.connect(dbfile) as db:
            db.execute("UPDATE collections SET payload='{}'")
        with pytest.raises(StorageError,match='integrity'):
            read(store)

@pytest.mark.parametrize('reference',["https://user:placeholder@example.invalid/report","https://example.invalid/report?access_token=placeholder","https://example.invalid/report#private","https://example.invalid/report?unreviewed=placeholder"])
def test_bad_source_references_rejected(store,reference):
    old=observation()
    obj=replace(old,provenance=replace(old.provenance,source=replace(old.provenance.source,reference=reference)))
    with pytest.raises(StorageError): store.ingest('abc',obj)
    assert read(store)==()


def test_mutated_contract_does_not_get_in(store):
    x=observation()
    object.__setattr__(x,'value',1.2)
    with pytest.raises(StorageError): store.ingest('abc',x)
    assert read(store)==()


def test_price_special_metadata_roundtrip(store):
    v=observation()
    p=replace(v,kind=RecordKind.PRICE,metric='regular_market_price',value=Decimal('0'),unit='currency/share',currency='BRL',adjustment='provider_unspecified')
    r=store.ingest('price',p)
    assert read(store,p)==(r,)


def test_null_batch_and_invalid_query(store):
    assert store.ingest_many([])==()
    with pytest.raises(StorageError): read(store,version=0)


def test_query_through_tampered_economic_row_detected(dbfile):
    with ObservationStore.local(dbfile,scope=SCOPE,synthetic=True,create=True) as db:
        db.ingest('abc',observation())
        with sqlite3.connect(dbfile) as outside:
            outside.execute("UPDATE versions SET economic='{}'")
        with pytest.raises(StorageError): read(db)
