"""Audit hash-chain invariants (pure — no DB)."""

from app.services.audit import _hash


def test_hash_is_deterministic():
    a = _hash(None, case_id="abc", actor="SYSTEM", event_type="CASE_CREATED", detail={"x": 1})
    b = _hash(None, case_id="abc", actor="SYSTEM", event_type="CASE_CREATED", detail={"x": 1})
    assert a == b


def test_hash_changes_with_detail():
    a = _hash(None, case_id="abc", actor="SYSTEM", event_type="CASE_CREATED", detail={"x": 1})
    b = _hash(None, case_id="abc", actor="SYSTEM", event_type="CASE_CREATED", detail={"x": 2})
    assert a != b


def test_hash_chains_prev():
    h0 = _hash(None, case_id="abc", actor="SYSTEM", event_type="CASE_CREATED", detail={})
    h1 = _hash(h0, case_id="abc", actor="SYSTEM", event_type="STATE_TRANSITION", detail={})
    h1_bad = _hash("tampered", case_id="abc", actor="SYSTEM", event_type="STATE_TRANSITION", detail={})
    assert h1 != h1_bad


def test_hash_is_sha256_length():
    h = _hash(None, case_id=None, actor="SYSTEM", event_type="X", detail={})
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
