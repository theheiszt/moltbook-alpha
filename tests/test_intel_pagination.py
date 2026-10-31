import base64
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api_server import app, storage
from routes.pagination import MAX_CURSOR_OFFSET, decode_cursor, encode_cursor, paginate


def _raw_cursor(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


@pytest.mark.parametrize("offset", [0, 1, 3, 99, MAX_CURSOR_OFFSET])
def test_cursor_round_trip(offset):
    cursor = encode_cursor(offset)
    assert "=" not in cursor
    assert decode_cursor(cursor) == offset


@pytest.mark.parametrize(
    "cursor",
    [
        "!!!not-base64!!!",
        _raw_cursor("not json"),
        _raw_cursor("[1, 2]"),
        _raw_cursor('{"x": 3}'),
        _raw_cursor('{"o": "3"}'),
        _raw_cursor('{"o": 1.5}'),
        _raw_cursor('{"o": true}'),
        _raw_cursor('{"o": -1}'),
        _raw_cursor('{"o": %d}' % (MAX_CURSOR_OFFSET + 1)),
        _raw_cursor("\xff\xfe"),
    ],
)
def test_invalid_cursor_rejected(cursor):
    with pytest.raises(HTTPException) as exc:
        decode_cursor(cursor)
    assert exc.value.status_code == 400


def test_paginate_slices_and_signals_more():
    items, nxt = paginate(list(range(7)), 0, 3)
    assert items == [0, 1, 2] and decode_cursor(nxt) == 3
    items, nxt = paginate(list(range(7)), 6, 3)
    assert items == [6] and nxt is None


def _fake(n):
    return [{"id": i} for i in range(n)]


def _fake_engine(n, calls):
    def fn(*args, **kwargs):
        calls.append(kwargs["limit"])
        return _fake(n)[: kwargs["limit"]]
    return fn


@pytest.mark.parametrize(
    "path, engine_fn, list_key",
    [
        ("/v1/intel/signals", "search_signals", "signals"),
        ("/v1/intel/opportunities", "get_live_opportunities", "opportunities"),
    ],
)
def test_route_walks_pages_with_next_cursor(path, engine_fn, list_key):
    client = TestClient(app, raise_server_exceptions=False)
    raw_key, _ = storage.create_api_key(tier="tier_starter", credits=50, prefix_tag="molt_page_test")
    headers = {"X-API-KEY": raw_key}
    calls = []

    with patch(f"routes.intel.intel_engine.{engine_fn}", side_effect=_fake_engine(7, calls)):
        first = client.get(path, headers=headers, params={"limit": 3})
        assert first.status_code == 200, first.text
        body = first.json()
        assert [x["id"] for x in body[list_key]] == [0, 1, 2]
        assert body["count"] == 3 and body["next_cursor"]

        second = client.get(path, headers=headers, params={"limit": 3, "cursor": body["next_cursor"]}).json()
        assert [x["id"] for x in second[list_key]] == [3, 4, 5] and second["next_cursor"]

        third = client.get(path, headers=headers, params={"limit": 3, "cursor": second["next_cursor"]}).json()
        assert [x["id"] for x in third[list_key]] == [6]
        assert third["count"] == 1 and third["next_cursor"] is None

    # Engine is asked for exactly one row past the page so "more?" is known.
    assert calls == [4, 7, 10]
    assert storage.get_key_quota_details(raw_key)["credits_remaining"] == 47


def test_default_request_without_cursor_unchanged():
    client = TestClient(app, raise_server_exceptions=False)
    raw_key, _ = storage.create_api_key(tier="tier_starter", credits=5, prefix_tag="molt_page_test")
    with patch("routes.intel.intel_engine.search_signals", side_effect=_fake_engine(10, [])):
        body = client.get("/v1/intel/signals", headers={"X-API-KEY": raw_key}).json()
    assert body["count"] == 10 and body["next_cursor"] is None


def test_garbage_cursor_is_400_and_not_charged():
    client = TestClient(app, raise_server_exceptions=False)
    raw_key, _ = storage.create_api_key(tier="tier_starter", credits=5, prefix_tag="molt_page_test")
    resp = client.get("/v1/intel/signals", headers={"X-API-KEY": raw_key}, params={"cursor": "garbage!"})
    assert resp.status_code == 400
    assert storage.get_key_quota_details(raw_key)["credits_remaining"] == 5
