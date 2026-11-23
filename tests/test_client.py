from __future__ import annotations

import pytest

from baleia_openmetadata.client import (
    BaleiaAuthError,
    BaleiaClient,
    BaleiaContractError,
    BaleiaError,
)
from baleia_openmetadata.config import BaleiaConfig

from .conftest import FakeGateway

SUMMARY = {
    "contract_version": 1,
    "workspace": {"id": "w", "name": "Sales"},
    "models": 3,
    "metrics": 0,
}


def client_for(gateway: FakeGateway, sleeps: list[float] | None = None) -> BaleiaClient:
    cfg = BaleiaConfig.from_options(
        {
            "baleiaUrl": gateway.url,
            "allowHttp": "true",
            "biKeyEmail": "owner@example.com",
            "biKey": "bal_secret",
            "trinoServiceNames": "trino",
            "timeoutSeconds": "5",
        },
        env={},
    )
    recorded = sleeps if sleeps is not None else []
    return BaleiaClient(cfg, sleep=recorded.append)


def test_summary_sends_the_bi_key(gateway: FakeGateway) -> None:
    gateway.json("/baleia/v1/semantic", SUMMARY)
    assert client_for(gateway).summary()["models"] == 3
    path, _, auth = gateway.requests[0]
    assert path == "/baleia/v1/semantic"
    assert auth == "owner@example.com:bal_secret"


def test_models_follow_pages(gateway: FakeGateway) -> None:
    pages = {
        "": {"contract_version": 1, "items": [{"slug": "a"}, {"slug": "b"}], "next_after": "b"},
        "b": {"contract_version": 1, "items": [{"slug": "c"}]},
    }
    gateway.route(
        "/baleia/v1/semantic/models", lambda params: (200, {}, pages[params.get("after", "")])
    )
    assert [m["slug"] for m in client_for(gateway).models()] == ["a", "b", "c"]
    assert [params for _, params, _ in gateway.requests] == [
        {"limit": "500"},
        {"limit": "500", "after": "b"},
    ]


def test_metrics_empty(gateway: FakeGateway) -> None:
    gateway.json("/baleia/v1/semantic/metrics", {"contract_version": 1, "items": []})
    assert list(client_for(gateway).metrics()) == []


def test_retries_transient_failures(gateway: FakeGateway) -> None:
    replies = [(503, {}, {}), (429, {"Retry-After": "2"}, {}), (200, {}, SUMMARY)]
    gateway.route("/baleia/v1/semantic", lambda _params: replies.pop(0))
    sleeps: list[float] = []
    assert client_for(gateway, sleeps).summary()["contract_version"] == 1
    assert sleeps == [0.5, 2.0]


def test_gives_up_after_bounded_attempts(gateway: FakeGateway) -> None:
    gateway.route("/baleia/v1/semantic", lambda _params: (503, {}, {}))
    with pytest.raises(BaleiaError, match="HTTP 503"):
        client_for(gateway).summary()
    assert len(gateway.requests) == 3


def test_refused_key_never_leaks(gateway: FakeGateway) -> None:
    gateway.json("/baleia/v1/semantic", {"error": "invalid"}, status=401)
    with pytest.raises(BaleiaAuthError) as err:
        client_for(gateway).summary()
    assert "bal_secret" not in str(err.value)
    assert len(gateway.requests) == 1


def test_unsupported_contract(gateway: FakeGateway) -> None:
    gateway.json("/baleia/v1/semantic", {**SUMMARY, "contract_version": 2})
    with pytest.raises(BaleiaContractError, match="2"):
        client_for(gateway).summary()


def test_old_baleia_without_routes(gateway: FakeGateway) -> None:
    with pytest.raises(BaleiaError, match="404"):
        client_for(gateway).summary()


def test_redirects_are_not_followed(gateway: FakeGateway) -> None:
    gateway.route(
        "/baleia/v1/semantic", lambda _params: (302, {"Location": "http://elsewhere.test/"}, {})
    )
    with pytest.raises(BaleiaError, match="HTTP 302"):
        client_for(gateway).summary()


def test_unreachable_gateway() -> None:
    cfg = BaleiaConfig.from_options(
        {
            "baleiaUrl": "http://127.0.0.1:9",
            "allowHttp": "true",
            "biKeyEmail": "owner@example.com",
            "biKey": "bal_secret",
            "trinoServiceNames": "trino",
            "timeoutSeconds": "1",
        },
        env={},
    )
    sleeps: list[float] = []
    with pytest.raises(BaleiaError, match="unreachable") as err:
        BaleiaClient(cfg, sleep=sleeps.append).summary()
    assert "bal_secret" not in str(err.value)
    assert len(sleeps) == 2


def test_repeated_cursor_is_rejected(gateway: FakeGateway) -> None:
    page = {"contract_version": 1, "items": [{"slug": "a"}], "next_after": "a"}
    gateway.route("/baleia/v1/semantic/models", lambda _params: (200, {}, page))
    with pytest.raises(BaleiaError, match="repeated page cursor"):
        list(client_for(gateway).models())
    assert len(gateway.requests) == 2


def test_retry_after_http_date(gateway: FakeGateway) -> None:
    from datetime import datetime, timezone

    now = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)
    replies = [(503, {"Retry-After": "Tue, 24 Nov 2026 12:00:04 GMT"}, {}), (200, {}, SUMMARY)]
    gateway.route("/baleia/v1/semantic", lambda _params: replies.pop(0))
    sleeps: list[float] = []
    client = client_for(gateway, sleeps)
    client._now = lambda: now
    client.summary()
    assert sleeps == [4.0]
