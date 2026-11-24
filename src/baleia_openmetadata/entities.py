"""Mapping from Baleia's semantic catalog to OpenMetadata create requests.

Every function here is pure: it turns one catalog item into the request
OpenMetadata upserts by name, so a run with no change in Baleia changes
nothing in OpenMetadata.

Naming rules (stable across runs, never derived from user-edited labels):

- A semantic model becomes a ``DashboardDataModel`` named after its slug,
  under the workspace's dashboard service.
- ``Metric`` is a global entity in OpenMetadata, so a metric's name carries the
  service name: ``<service>__<slug>`` for a standalone metric and
  ``<service>__<model slug>__<metric name>`` for a metric defined in a model.
"""

from __future__ import annotations

from typing import Any

from metadata.generated.schema.api.data.createDashboardDataModel import (
    CreateDashboardDataModelRequest,
)
from metadata.generated.schema.api.data.createMetric import CreateMetricRequest
from metadata.generated.schema.entity.data.dashboardDataModel import DataModelType
from metadata.generated.schema.entity.data.metric import Language, MetricExpression
from metadata.generated.schema.entity.data.table import Column, DataType

# Separator between the parts of a metric name. Dots would be quoted in fully
# qualified names, so a double underscore keeps names plain.
NAME_SEPARATOR = "__"

# Baleia's logical types (internal/dialect) to OpenMetadata column types.
# Anything else falls back to UNKNOWN and keeps the Baleia type for display.
_DATA_TYPES: dict[str, DataType] = {
    "boolean": DataType.BOOLEAN,
    "int64": DataType.BIGINT,
    "float64": DataType.DOUBLE,
    "string": DataType.STRING,
    "date": DataType.DATE,
    "timestamp": DataType.TIMESTAMP,
    "timestamptz": DataType.TIMESTAMPZ,
    "binary": DataType.BINARY,
    "json": DataType.JSON,
}

# Model metrics are aggregates: OpenMetadata shows them as numeric columns.
METRIC_COLUMN_TYPE = DataType.NUMBER


def data_type(baleia_type: str | None) -> DataType:
    """Maps a Baleia logical type to an OpenMetadata column type."""
    return _DATA_TYPES.get((baleia_type or "").strip().lower(), DataType.UNKNOWN)


def metric_name(service: str, *parts: str) -> str:
    """The global name of a metric of ``service``."""
    return NAME_SEPARATOR.join([service, *parts])


def _text(value: Any) -> str | None:
    text = value.strip() if isinstance(value, str) else ""
    return text or None


def data_model_request(
    model: dict[str, Any], service: str, model_type: DataModelType, project: str | None
) -> CreateDashboardDataModelRequest:
    """The data model of one Baleia semantic model.

    Columns are the model's visible dimensions, then its metrics as numeric
    columns. A name used twice keeps its first column.
    """
    slug = model["slug"]
    columns: list[Column] = []
    seen: set[str] = set()
    for dim in model.get("columns") or []:
        name = dim["name"]
        if name in seen:
            continue
        seen.add(name)
        baleia_type = dim.get("type") or ""
        columns.append(
            Column(
                name=name,
                displayName=_text(dim.get("label")),
                description=_text(dim.get("description")),
                dataType=data_type(baleia_type),
                dataTypeDisplay=baleia_type or None,
            )
        )
    for metric in model.get("metrics") or []:
        name = metric["name"]
        if name in seen:
            continue
        seen.add(name)
        columns.append(
            Column(
                name=name,
                displayName=_text(metric.get("label")),
                dataType=METRIC_COLUMN_TYPE,
                dataTypeDisplay="metric",
            )
        )
    source = model.get("source") or {}
    return CreateDashboardDataModelRequest(
        name=slug,
        displayName=_text(model.get("label")) or slug,
        description=_text(model.get("description")),
        service=service,
        dataModelType=model_type,
        columns=columns,
        sql=_text(source.get("sql")),
        sourceUrl=_text(model.get("url")),
        project=project,
    )


def model_metric_requests(model: dict[str, Any], service: str) -> list[CreateMetricRequest]:
    """The metrics defined inside one Baleia semantic model."""
    slug = model["slug"]
    out: list[CreateMetricRequest] = []
    for metric in model.get("metrics") or []:
        label = _text(metric.get("label")) or metric["name"]
        out.append(
            CreateMetricRequest(
                name=metric_name(service, slug, metric["name"]),
                displayName=label,
                description=f"Metric `{metric['name']}` of the Baleia model `{slug}`.",
                metricExpression=_expression(metric.get("sql")),
            )
        )
    return out


def metric_request(metric: dict[str, Any], service: str) -> CreateMetricRequest:
    """One standalone Baleia metric."""
    slug = metric["slug"]
    return CreateMetricRequest(
        name=metric_name(service, slug),
        displayName=_text(metric.get("label")) or slug,
        description=_text(metric.get("description")),
        metricExpression=_expression(metric.get("sql")),
    )


def _expression(sql: Any) -> MetricExpression | None:
    code = _text(sql)
    if code is None:
        return None
    return MetricExpression(language=Language.SQL, code=code)
