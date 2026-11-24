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
    serve_catalog(gateway, [], [])
    source = BaleiaSource.create(workflow_source(options_for(gateway)), MagicMock())
    source.test_connection()
    assert list(source._iter()) == []
    source.close()
    assert [path for path, _, _ in gateway.requests] == [
        "/baleia/v1/semantic",
        "/baleia/v1/semantic",
        "/baleia/v1/semantic/models",
        "/baleia/v1/semantic/metrics",
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


def serve_catalog(
    gateway: FakeGateway, models: list[dict[str, Any]], metrics: list[dict[str, Any]]
) -> None:
    gateway.json(
        "/baleia/v1/semantic",
        {
            "contract_version": 1,
            "workspace": {"id": "w", "name": "Sales"},
            "models": len(models),
            "metrics": len(metrics),
        },
    )
    gateway.json("/baleia/v1/semantic/models", {"contract_version": 1, "items": models})
    gateway.json("/baleia/v1/semantic/metrics", {"contract_version": 1, "items": metrics})


def test_run_yields_data_models_and_metrics(gateway: FakeGateway) -> None:
    from metadata.generated.schema.api.data.createDashboardDataModel import (
        CreateDashboardDataModelRequest,
    )
    from metadata.generated.schema.api.data.createMetric import CreateMetricRequest

    from .catalog import METRIC, MODEL

    serve_catalog(gateway, [MODEL], [METRIC])
    source = BaleiaSource.create(workflow_source(options_for(gateway)), MagicMock())
    results = list(source._iter())
    assert all(r.left is None for r in results)
    rights = [r.right for r in results]
    assert isinstance(rights[0], CreateDashboardDataModelRequest)
    assert rights[0].name.root == "orders"
    assert rights[0].project == "Sales"
    metrics = [r.name.root for r in rights if isinstance(r, CreateMetricRequest)]
    assert metrics == [
        "baleia-sales__orders__order_count",
        "baleia-sales__orders__orderkey",
        "baleia-sales__order_count",
    ]


def test_a_bad_item_does_not_stop_the_run(gateway: FakeGateway) -> None:
    from .catalog import METRIC

    serve_catalog(gateway, [{"label": "no slug"}], [METRIC])
    source = BaleiaSource.create(workflow_source(options_for(gateway)), MagicMock())
    results = list(source._iter())
    assert results[0].left is not None
    assert "data model None" in results[0].left.name
    assert results[-1].right.name.root == "baleia-sales__order_count"


def test_invalid_data_model_type(gateway: FakeGateway) -> None:
    options = {**options_for(gateway), "dataModelType": "NotAType"}
    with pytest.raises(InvalidSourceException, match="dataModelType"):
        BaleiaSource.create(workflow_source(options), MagicMock())


def test_custom_data_model_type(gateway: FakeGateway) -> None:
    from metadata.generated.schema.entity.data.dashboardDataModel import DataModelType

    options = {**options_for(gateway), "dataModelType": "OmniDataModel"}
    source = BaleiaSource.create(workflow_source(options), MagicMock())
    assert source.data_model_type is DataModelType.OmniDataModel
