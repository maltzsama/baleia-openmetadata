from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from metadata.generated.schema.entity.services.dashboardService import DashboardService
from metadata.generated.schema.type.basic import EntityName
from metadata.ingestion.api.steps import InvalidSourceException

from baleia_openmetadata.source import BaleiaSource

from .conftest import FakeGateway


def workflow_source(options: dict[str, str], mark_deleted: bool = True) -> dict[str, Any]:
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
        "sourceConfig": {
            "config": {"type": "DashboardMetadata", "markDeletedDataModels": mark_deleted}
        },
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
    source = BaleiaSource.create(workflow_source(options_for(gateway)), fake_metadata([], []))
    source.test_connection()
    assert [type(r.right).__name__ for r in source._iter()] == ["Barrier"]
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
    source = BaleiaSource.create(workflow_source(options_for(gateway)), fake_metadata([], []))
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
    source = BaleiaSource.create(workflow_source(options_for(gateway)), fake_metadata([], []))
    results = list(source._iter())
    assert results[0].left is not None
    assert "data model None" in results[0].left.name
    created = [r.right for r in results if type(r.right).__name__ == "CreateMetricRequest"]
    assert created[-1].name.root == "baleia-sales__order_count"


def test_invalid_data_model_type(gateway: FakeGateway) -> None:
    options = {**options_for(gateway), "dataModelType": "NotAType"}
    with pytest.raises(InvalidSourceException, match="dataModelType"):
        BaleiaSource.create(workflow_source(options), MagicMock())


def test_custom_data_model_type(gateway: FakeGateway) -> None:
    from metadata.generated.schema.entity.data.dashboardDataModel import DataModelType

    options = {**options_for(gateway), "dataModelType": "OmniDataModel"}
    source = BaleiaSource.create(workflow_source(options), MagicMock())
    assert source.data_model_type is DataModelType.OmniDataModel


def fake_metadata(existing_models: list[str], existing_metrics: list[str]) -> MagicMock:
    """OpenMetadata as the source sees it once the sink wrote its entities.

    Any data model or metric the source looks up exists; the Trino table
    ``trino-sales.e2e_tpch.tiny.orders`` exists; ``existing_*`` are extra
    entities from earlier runs.
    """
    from types import SimpleNamespace

    from metadata.generated.schema.entity.data.dashboardDataModel import DashboardDataModel
    from metadata.generated.schema.entity.data.metric import Metric

    counter = iter(range(1, 10_000))

    def new_id() -> str:
        return f"00000000-0000-4000-8000-{next(counter):012d}"

    tables = {"trino-sales.e2e_tpch.tiny.orders": SimpleNamespace(id=new_id())}
    models: dict[str, DashboardDataModel] = {}
    metrics: dict[str, Metric] = {}

    def model(fqn: str) -> DashboardDataModel:
        name = fqn.rsplit(".", 1)[-1]
        return models.setdefault(
            fqn,
            DashboardDataModel.model_construct(
                id=new_id(), name=EntityName(name), fullyQualifiedName=fqn
            ),
        )

    def metric(fqn: str) -> Metric:
        return metrics.setdefault(
            fqn, Metric.model_construct(id=new_id(), name=EntityName(fqn), fullyQualifiedName=fqn)
        )

    for name in existing_models:
        model(f"baleia-sales.model.{name}")
    for name in existing_metrics:
        metric(name)

    def get_by_name(entity: object, fqn: str) -> object:
        if entity is DashboardDataModel:
            return model(fqn)
        if entity is Metric:
            return metric(fqn)
        return tables.get(fqn)

    def list_all(entity: object, params: dict[str, str] | None = None) -> list[object]:
        return list(models.values()) if entity is DashboardDataModel else list(metrics.values())

    metadata = MagicMock()
    metadata.get_by_name.side_effect = get_by_name
    metadata.list_all_entities.side_effect = list_all
    metadata.get_lineage_by_id.return_value = {"upstreamEdges": []}
    return metadata


def test_run_flushes_then_links_then_soft_deletes(gateway: FakeGateway) -> None:
    from metadata.generated.schema.api.lineage.addLineage import AddLineageRequest
    from metadata.ingestion.models.barrier import Barrier
    from metadata.ingestion.models.delete_entity import DeleteEntity

    from .catalog import METRIC, MODEL

    serve_catalog(gateway, [MODEL], [METRIC])
    metadata = fake_metadata(
        existing_models=["orders", "removed_model"], existing_metrics=["baleia-sales__removed"]
    )
    source = BaleiaSource.create(workflow_source(options_for(gateway)), metadata)
    records = [r.right for r in source._iter()]
    kinds = [type(r).__name__ for r in records]
    barrier = kinds.index("Barrier")
    assert all(k.startswith("Create") for k in kinds[:barrier])
    assert isinstance(records[barrier], Barrier)
    lineage = [r for r in records if isinstance(r, AddLineageRequest)]
    # table -> data model, data model -> its two metrics, table -> standalone metric
    assert [(e.edge.fromEntity.type, e.edge.toEntity.type) for e in lineage] == [
        ("table", "dashboardDataModel"),
        ("dashboardDataModel", "metric"),
        ("dashboardDataModel", "metric"),
        ("table", "metric"),
    ]
    deleted = sorted(r.entity.name.root for r in records if isinstance(r, DeleteEntity))
    assert deleted == ["baleia-sales__removed", "removed_model"]
    assert kinds.index("DeleteEntity") > kinds.index("AddLineageRequest")


def test_unresolved_tables_are_warnings(gateway: FakeGateway) -> None:
    from .catalog import MODEL

    model = {**MODEL, "source_tables": ["e2e_tpch.tiny.unknown"]}
    serve_catalog(gateway, [model], [])
    source = BaleiaSource.create(workflow_source(options_for(gateway)), fake_metadata([], []))
    results = list(source._iter())
    assert all(r.left is None for r in results)
    assert any("e2e_tpch.tiny.unknown" in str(w) for w in source.status.warnings)


def test_mark_deleted_off_keeps_everything(gateway: FakeGateway) -> None:
    from metadata.ingestion.models.delete_entity import DeleteEntity

    serve_catalog(gateway, [], [])
    metadata = fake_metadata(
        existing_models=["removed_model"], existing_metrics=["baleia-sales__removed"]
    )
    source = BaleiaSource.create(
        workflow_source(options_for(gateway), mark_deleted=False), metadata
    )
    assert not any(isinstance(r.right, DeleteEntity) for r in source._iter())


def test_failed_read_deletes_nothing(gateway: FakeGateway) -> None:
    from baleia_openmetadata.client import BaleiaError

    gateway.json(
        "/baleia/v1/semantic",
        {"contract_version": 1, "workspace": {"id": "w"}, "models": 1, "metrics": 0},
    )
    gateway.json("/baleia/v1/semantic/models", {"contract_version": 1, "items": []})
    gateway.route("/baleia/v1/semantic/metrics", lambda _params: (500, {}, {}))
    metadata = fake_metadata(existing_models=["removed_model"], existing_metrics=[])
    source = BaleiaSource.create(workflow_source(options_for(gateway)), metadata)
    source.client._sleep = lambda _seconds: None
    with pytest.raises(BaleiaError):
        list(source._iter())
    metadata.list_all_entities.assert_not_called()


def test_service_name_with_separator_is_refused(gateway: FakeGateway) -> None:
    config = workflow_source(options_for(gateway))
    config["serviceName"] = "sales__eu"
    with pytest.raises(InvalidSourceException, match="must not contain"):
        BaleiaSource.create(config, MagicMock())
