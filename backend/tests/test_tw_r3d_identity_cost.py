"""Exact pre-R3D canonical bytes and bounded normalization work."""
from datetime import timedelta
from decimal import Decimal
from enum import Enum, IntEnum
from hashlib import sha256
import json
from unittest.mock import patch

import pytest

from app.market import tw_bar_identity as owner
from test_tw_bar_identity import INSTRUMENT, _bar
from test_tw_r3_technical_cost import reference_canonical


def inputs(size):
    bar = _bar(provider='fixture', source='fixture-bars', content_hash='h')
    bars = tuple(bar.model_copy(update={
        'start_at': bar.start_at + timedelta(days=i),
        'end_at': bar.end_at + timedelta(days=i),
        'turnover_value': Decimal('-0') if i % 2 else None,
        'trade_count': 0 if i % 2 else None,
        'lineage': bar.lineage.model_copy(update={'content_hash': f'h-{i}'})}) for i in range(size))
    class Text(str, Enum): READY = 'ready'
    class Count(IntEnum): ZERO = 0
    class CustomText(str): pass
    class CustomInt(int): pass
    class CustomFloat(float): pass
    return dict(instrument=INSTRUMENT, requested_interval='1d', base_interval='1d', bars=bars,
        coverage=(), aggregation_version=None,
        state={'receipt': bar.start_at, 'nested': [Decimal('-0'), Text.READY, Count.ZERO,
            CustomText('lineage'), CustomInt(3), CustomFloat(-0.0), {'limitation': ['unknown']} ]})


@pytest.mark.parametrize('size', [1800, 5000])
def test_four_canonical_payload_bytes_and_hashes_match_frozen_owner(size):
    args = inputs(size)
    # Frozen pre-R3D owner payload construction plus independent canonicalizer.
    instrument = owner._instrument(args['instrument'])
    payloads = [
        {'contract_version': owner.TAIWAN_BAR_FINGERPRINT_VERSION, 'instrument': instrument,
         'requested_interval': '1d', 'base_interval': '1d',
         'bars': [owner._semantic_bar(bar, aggregation_version=None) for bar in args['bars']]},
        {'contract_version': owner.TAIWAN_BAR_LINEAGE_DIGEST_VERSION, 'instrument': instrument,
         'bars': [owner._lineage_bar(bar) for bar in args['bars']]},
        {'contract_version': owner.TAIWAN_BAR_STATE_DIGEST_VERSION, 'instrument': instrument,
         'finalization': [bar.finalization.value for bar in args['bars']], 'coverage': [], 'state': args['state']},
    ]
    encode = lambda value: json.dumps(reference_canonical(value), ensure_ascii=False,
                                    sort_keys=True, separators=(',', ':')).encode('utf-8')
    expected_bytes = [encode(value) for value in payloads]
    expected_hashes = [sha256(value).hexdigest() for value in expected_bytes]
    expected_bytes.append(encode({'contract_version': owner.TAIWAN_BAR_SERIES_REVISION_VERSION,
        'series_fingerprint': expected_hashes[0], 'lineage_digest': expected_hashes[1],
        'state_digest': expected_hashes[2]}))
    expected_hashes.append(sha256(expected_bytes[-1]).hexdigest())
    serialized = []
    dumps = json.dumps
    def capture(*a, **kw):
        encoded = dumps(*a, **kw)
        serialized.append(encoded.encode('utf-8'))
        return encoded
    with patch.object(owner.json, 'dumps', side_effect=capture):
        result = owner.build_taiwan_bar_series_identity(**args)
    assert serialized == expected_bytes
    assert [getattr(result, key) for key in ('series_fingerprint','lineage_digest','state_digest','series_revision')] == expected_hashes
    assert args['state']['nested'][-1]['limitation'] == ['unknown']


@pytest.mark.parametrize('size', [1800, 5000])
def test_pre_normalized_payloads_do_not_repeat_recursive_normalization(size, record_property):
    calls = 0
    original = owner._canonical
    def count(value):
        nonlocal calls
        calls += 1
        return original(value)
    with patch.object(owner, '_canonical', side_effect=count):
        owner.build_taiwan_bar_series_identity(**inputs(size))
    record_property('history_bars', size)
    record_property('canonical_call_count', calls)
    # State still traverses every finalization and generic nested value. The
    # semantic/lineage primitives must not trigger ~26 extra visits per bar.
    assert size < calls < size + 100
