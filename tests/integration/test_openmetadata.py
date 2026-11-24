"""The connector against a real OpenMetadata server.

One scenario, three runs of the ingestion workflow against a stand-in for
Baleia's BI gateway: a full catalog, a catalog that lost items and a
dependency, and the full catalog again.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from ..catalog import METRIC, MODEL, SQL_MODEL, UNRENDERED_METRIC
from ..conftest import FakeGateway
from .conftest import OpenMetadataServer

pytestmark = pytest.mark.integration


def serve(
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


def run_workflow(
    openmetadata: OpenMetadataServer, gateway: FakeGateway, names: dict[str, str]
) -> None:
    from metadata.workflow.metadata import MetadataWorkflow

    workflow = MetadataWorkflow.create(
        {
            "source": {
                "type": "customdashboard",
                "serviceName": names["dashboard"],
                "serviceConnection": {
                    "config": {
                        "type": "CustomDashboard",
                        "sourcePythonClass": "baleia_openmetadata.source.BaleiaSource",
                        "connectionOptions": {
                            "baleiaUrl": gateway.url,
                            "allowHttp": "true",
                            "biKeyEmail": "owner@example.com",
                            "trinoServiceNames": names["trino"],
                        },
                    }
                },
                "sourceConfig": {"config": {"type": "DashboardMetadata"}},
            },
            "sink": {"type": "metadata-rest", "config": {}},
            "workflowConfig": {
                "loggerLevel": "INFO",
                "openMetadataServerConfig": {
                    "hostPort": f"{openmetadata.url}/api",
                    "authProvider": "openmetadata",
                    "securityConfig": {"jwtToken": openmetadata.token},
                },
            },
        }
    )
    workflow.execute()
    workflow.raise_from_status()
    workflow.stop()


def data_models(
    om: OpenMetadataServer, service: str, include: str = "non-deleted"
) -> dict[str, Any]:
    body = om.get(
        "/dashboard/datamodels", service=service, fields="columns", include=include, limit=100
    )
    return {m["name"]: m for m in body["data"]}


def metrics(om: OpenMetadataServer, service: str, include: str = "non-deleted") -> dict[str, Any]:
    body = om.get("/metrics", include=include, limit=1000)
    return {m["name"]: m for m in body["data"] if m["name"].startswith(f"{service}__")}


def downstream_of(om: OpenMetadataServer, table_fqn: str) -> set[str]:
    lineage = om.get(f"/lineage/table/name/{table_fqn}", upstreamDepth=0, downstreamDepth=1)
    return {n["fullyQualifiedName"] for n in lineage.get("nodes") or []}


def test_connector_end_to_end(
    openmetadata: OpenMetadataServer,
    gateway: FakeGateway,
    names: dict[str, str],
    trino_orders: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BALEIA_BI_KEY", "bal_secret")
    om, service = openmetadata, names["dashboard"]

    # 1. The full catalog.
    serve(gateway, [MODEL, SQL_MODEL], [METRIC, UNRENDERED_METRIC])
    run_workflow(om, gateway, names)

    stored = om.get(f"/services/dashboardServices/name/{service}")
    assert stored["serviceType"] == "CustomDashboard"
    assert "biKey" not in stored["connection"]["config"]["connectionOptions"]

    models = data_models(om, service)
    assert set(models) == {"orders", "big_orders"}
    assert models["orders"]["dataModelType"] == "LookMlView"
    assert [(c["name"], c["dataType"]) for c in models["orders"]["columns"]] == [
        ("orderkey", "BIGINT"),
        ("order_status", "STRING"),
        ("payload", "UNKNOWN"),
        ("order_count", "NUMBER"),
    ]
    assert models["big_orders"]["sql"].startswith("SELECT * FROM tiny.orders")

    found = metrics(om, service)
    assert set(found) == {
        f"{service}__order_count",
        f"{service}__elsewhere",
        f"{service}__orders__order_count",
        f"{service}__orders__orderkey",
    }
    assert found[f"{service}__order_count"]["metricExpression"]["language"] == "SQL"

    assert downstream_of(om, trino_orders) == {
        f"{service}.model.orders",
        f"{service}.model.big_orders",
        f"{service}__order_count",
    }
    model_lineage = om.get(
        f"/lineage/metric/name/{service}__orders__order_count", upstreamDepth=1, downstreamDepth=0
    )
    assert {n["fullyQualifiedName"] for n in model_lineage["nodes"]} == {f"{service}.model.orders"}

    versions = {name: m["version"] for name, m in data_models(om, service).items()}
    run_workflow(om, gateway, names)
    assert {name: m["version"] for name, m in data_models(om, service).items()} == versions

    # 2. Baleia lost a model and the standalone metrics, and orders reads no table.
    serve(gateway, [{**MODEL, "source_tables": []}], [])
    run_workflow(om, gateway, names)
    assert set(data_models(om, service)) == {"orders"}
    assert set(data_models(om, service, include="deleted")) == {"big_orders"}
    assert set(metrics(om, service, include="deleted")) == {
        f"{service}__order_count",
        f"{service}__elsewhere",
    }
    assert f"{service}.model.orders" not in downstream_of(om, trino_orders)

    # 3. Everything comes back.
    serve(gateway, [MODEL, SQL_MODEL], [METRIC, UNRENDERED_METRIC])
    run_workflow(om, gateway, names)
    assert set(data_models(om, service)) == {"orders", "big_orders"}
    assert len(metrics(om, service)) == 4
    assert f"{service}.model.orders" in downstream_of(om, trino_orders)

    service_id = stored["id"]
    om.delete(f"/services/dashboardServices/{service_id}", recursive="true", hardDelete="true")
    for metric in metrics(om, service, include="all").values():
        om.delete(f"/metrics/{metric['id']}", hardDelete="true")


@pytest.mark.skipif(not os.environ.get("OPENMETADATA_URL"), reason="OPENMETADATA_URL is not set")
def test_server_is_reachable(openmetadata: OpenMetadataServer) -> None:
    assert openmetadata.get("/system/version")["version"]
