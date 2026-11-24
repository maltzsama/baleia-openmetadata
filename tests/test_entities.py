from __future__ import annotations

from metadata.generated.schema.entity.data.dashboardDataModel import DataModelType
from metadata.generated.schema.entity.data.metric import Language
from metadata.generated.schema.entity.data.table import DataType

from baleia_openmetadata.entities import (
    data_model_request,
    data_type,
    metric_name,
    metric_request,
    model_metric_requests,
)

from .catalog import METRIC, MODEL, SQL_MODEL, UNRENDERED_METRIC


def test_data_types() -> None:
    assert data_type("int64") is DataType.BIGINT
    assert data_type("TimestampTZ") is DataType.TIMESTAMPZ
    assert data_type("geometry") is DataType.UNKNOWN
    assert data_type(None) is DataType.UNKNOWN


def test_table_model() -> None:
    req = data_model_request(MODEL, "baleia-sales", DataModelType.LookMlView, "Sales")
    assert req.name.root == "orders"
    assert req.displayName == "Orders"
    assert req.description.root == "Orders exposed to external catalogs."
    assert req.service.root == "baleia-sales"
    assert req.dataModelType is DataModelType.LookMlView
    assert req.sql is None
    assert str(req.sourceUrl.root) == "https://baleia.example/models/m1"
    assert req.project == "Sales"
    cols = [(c.name.root, c.dataType, c.dataTypeDisplay) for c in req.columns]
    assert cols == [
        ("orderkey", DataType.BIGINT, "int64"),
        ("order_status", DataType.STRING, "string"),
        ("payload", DataType.UNKNOWN, "geometry"),
        ("order_count", DataType.NUMBER, "metric"),
    ]
    assert req.columns[1].displayName == "Order status"


def test_sql_model() -> None:
    req = data_model_request(SQL_MODEL, "baleia-sales", DataModelType.LookMlView, None)
    assert req.displayName == "big_orders"
    assert req.sql.root == "SELECT * FROM tiny.orders WHERE totalprice > 1000"
    assert req.columns == []


def test_model_metrics() -> None:
    reqs = model_metric_requests(MODEL, "baleia-sales")
    assert [r.name.root for r in reqs] == [
        "baleia-sales__orders__order_count",
        "baleia-sales__orders__orderkey",
    ]
    assert reqs[0].displayName == "Orders"
    assert reqs[0].metricExpression.language is Language.SQL
    assert "COUNT(*)" in reqs[0].metricExpression.code
    assert reqs[1].metricExpression is None


def test_standalone_metric() -> None:
    req = metric_request(METRIC, "baleia-sales")
    assert (
        req.name.root == metric_name("baleia-sales", "order_count") == "baleia-sales__order_count"
    )
    assert req.displayName == "Order count"
    assert req.description.root == "Orders, counted."
    assert req.metricExpression.code.startswith("SELECT COUNT(*)")
    assert metric_request(UNRENDERED_METRIC, "baleia-sales").metricExpression is None


def test_mapping_is_deterministic() -> None:
    first = data_model_request(MODEL, "s", DataModelType.LookMlView, "p").model_dump()
    second = data_model_request(MODEL, "s", DataModelType.LookMlView, "p").model_dump()
    assert first == second
