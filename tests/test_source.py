from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from metadata.generated.schema.entity.services.dashboardService import DashboardService
from metadata.ingestion.api.steps import InvalidSourceException

from baleia_openmetadata.source import BaleiaSource

from .conftest import FakeGateway


def workflow_source(options: dict[str, str]) -> dict[str, Any]:
    return {
        "type": "customdashboard",
        "serviceName": "baleia-sales",
        "serviceConnection": {
            "config": {
                "type": "CustomDashboard",
                "sourcePythonClass": "baleia_openmetadata.source.BaleiaSource",
                "connectionOptions": options,
            }
        },
        "sourceConfig": {"config": {"type": "DashboardMetadata"}},
    }


def options_for(gateway: FakeGateway) -> dict[str, str]:
    return {
        "baleiaUrl": gateway.url,
        "allowHttp": "true",
        "biKeyEmail": "owner@example.com",
        "biKey": "bal_secret",
        "trinoServiceNames": "trino-sales",
    }


def test_create_registers_the_dashboard_service(gateway: FakeGateway) -> None:
    metadata = MagicMock()
    source = BaleiaSource.create(workflow_source(options_for(gateway)), metadata)
    metadata.get_service_or_create.assert_called_once()
    assert metadata.get_service_or_create.call_args.kwargs["entity"] is DashboardService
    assert source.baleia.trino_services == ("trino-sales",)


def test_invalid_options_fail_creation(gateway: FakeGateway) -> None:
    options = {**options_for(gateway), "baleiaUrl": "not a url"}
    with pytest.raises(InvalidSourceException, match="baleiaUrl"):
        BaleiaSource.create(workflow_source(options), MagicMock())


def test_test_connection_and_run(gateway: FakeGateway) -> None:
    gateway.json(
        "/baleia/v1/semantic",
        {
            "contract_version": 1,
            "workspace": {"id": "w", "name": "Sales"},
            "models": 0,
            "metrics": 0,
        },
    )
    source = BaleiaSource.create(workflow_source(options_for(gateway)), MagicMock())
    source.test_connection()
    assert list(source._iter()) == []
    source.close()
    assert [path for path, _, _ in gateway.requests] == [
        "/baleia/v1/semantic",
        "/baleia/v1/semantic",
    ]


def test_service_is_registered_without_the_key(gateway: FakeGateway) -> None:
    gateway.json(
        "/baleia/v1/semantic",
        {"contract_version": 1, "workspace": {"id": "w"}, "models": 0, "metrics": 0},
    )
    metadata = MagicMock()
    source = BaleiaSource.create(workflow_source(options_for(gateway)), metadata)
    registered = metadata.get_service_or_create.call_args.kwargs["config"]
    options = registered.serviceConnection.root.config.connectionOptions.root
    assert "biKey" not in options
    assert options["biKeyEmail"] == "owner@example.com"
    # The source itself still authenticates with the key.
    source.test_connection()
    assert gateway.requests[0][2] == "owner@example.com:bal_secret"
