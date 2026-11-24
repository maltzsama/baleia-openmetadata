"""OpenMetadata source for Baleia's semantic catalog.

Register it under Dashboard Services > Custom with the source Python class
``baleia_openmetadata.source.BaleiaSource``.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable, Iterable
from typing import Any

from metadata.generated.schema.entity.data.dashboardDataModel import DataModelType
from metadata.generated.schema.entity.services.connections.dashboard import (
    customDashboardConnection,
)
from metadata.generated.schema.entity.services.dashboardService import DashboardService
from metadata.generated.schema.entity.services.ingestionPipelines.status import StackTraceError
from metadata.generated.schema.metadataIngestion.workflow import Source as WorkflowSource
from metadata.ingestion.api.models import Either
from metadata.ingestion.api.steps import InvalidSourceException, Source
from metadata.ingestion.ometa.ometa_api import OpenMetadata
from metadata.utils.logger import ingestion_logger

from baleia_openmetadata.client import BaleiaClient
from baleia_openmetadata.config import BaleiaConfig, ConfigError
from baleia_openmetadata.entities import data_model_request, metric_request, model_metric_requests

logger = ingestion_logger()


class BaleiaSource(Source):
    """Reads one Baleia workspace's semantic catalog into a dashboard service.

    One OpenMetadata dashboard service maps to one Baleia workspace: the
    workspace of the BI key in the connection options.
    """

    def __init__(
        self,
        config: WorkflowSource,
        metadata: OpenMetadata,
        client: BaleiaClient | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.metadata = metadata
        self.service_connection: customDashboardConnection.CustomDashboardConnection = (
            config.serviceConnection.root.config
        )
        options = self.service_connection.connectionOptions
        try:
            self.baleia = BaleiaConfig.from_options(options.root if options else None)
        except ConfigError as err:
            raise InvalidSourceException(f"Invalid Baleia connection options: {err}") from err
        try:
            self.data_model_type = DataModelType(self.baleia.data_model_type)
        except ValueError as err:
            raise InvalidSourceException(
                f"Invalid Baleia connection options: dataModelType {self.baleia.data_model_type!r} "
                "is not an OpenMetadata data model type"
            ) from err
        self.client = client or BaleiaClient(self.baleia)
        # The service is registered without the BI key: connection options are
        # stored as plain strings, not as secrets. The key stays in memory.
        self.dashboard_service: DashboardService = metadata.get_service_or_create(
            entity=DashboardService, config=_without_bi_key(config)
        )

    @classmethod
    def create(
        cls,
        config_dict: dict[str, Any],
        metadata: OpenMetadata,
        pipeline_name: str | None = None,
    ) -> BaleiaSource:
        config = WorkflowSource.model_validate(config_dict)
        connection = config.serviceConnection.root.config
        if not isinstance(connection, customDashboardConnection.CustomDashboardConnection):
            raise InvalidSourceException(
                f"Expected CustomDashboardConnection, but got {type(connection).__name__}"
            )
        return cls(config, metadata)

    def prepare(self) -> None:
        """Nothing to prepare: every run reads a fresh snapshot."""

    def test_connection(self) -> None:
        """Checks the gateway is reachable, the key is accepted and the contract is supported."""
        self.client.summary()

    @property
    def service_name(self) -> str:
        return self.config.serviceName

    def _iter(self, *_: Any, **__: Any) -> Iterable[Either]:
        summary = self.client.summary()
        workspace = summary.get("workspace") or {}
        project = workspace.get("name") or workspace.get("id")
        logger.info(
            "Baleia workspace %s: %s models, %s metrics",
            project,
            summary.get("models"),
            summary.get("metrics"),
        )
        service = self.service_name
        for model in self.client.models():
            yield _either(
                f"data model {model.get('slug')}",
                lambda m=model: data_model_request(m, service, self.data_model_type, project),
            )
            try:
                metric_requests = model_metric_requests(model, service)
            except Exception as err:
                yield _failure(f"metrics of model {model.get('slug')}", err)
                continue
            for request in metric_requests:
                yield Either(right=request)
        for metric in self.client.metrics():
            yield _either(
                f"metric {metric.get('slug')}", lambda m=metric: metric_request(m, service)
            )

    def close(self) -> None:
        self.client.close()


def _without_bi_key(config: WorkflowSource) -> WorkflowSource:
    """A copy of the workflow source whose connection options omit ``biKey``."""
    safe = config.model_copy(deep=True)
    options = safe.serviceConnection.root.config.connectionOptions
    if options is not None and options.root is not None:
        options.root.pop("biKey", None)
    return safe


def _either(name: str, build: Callable[[], Any]) -> Either:
    """Builds one request; a failure becomes a reported error, not a stopped run."""
    try:
        return Either(right=build())
    except Exception as err:
        return _failure(name, err)


def _failure(name: str, err: Exception) -> Either:
    return Either(
        left=StackTraceError(
            name=name,
            error=f"Cannot map Baleia {name}: {err}",
            stackTrace=traceback.format_exc(),
        )
    )
