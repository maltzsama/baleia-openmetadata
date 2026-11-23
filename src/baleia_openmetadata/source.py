"""OpenMetadata source for Baleia's semantic catalog.

Register it under Dashboard Services > Custom with the source Python class
``baleia_openmetadata.source.BaleiaSource``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from metadata.generated.schema.entity.services.connections.dashboard import (
    customDashboardConnection,
)
from metadata.generated.schema.entity.services.dashboardService import DashboardService
from metadata.generated.schema.metadataIngestion.workflow import Source as WorkflowSource
from metadata.ingestion.api.models import Either
from metadata.ingestion.api.steps import InvalidSourceException, Source
from metadata.ingestion.ometa.ometa_api import OpenMetadata
from metadata.utils.logger import ingestion_logger

from baleia_openmetadata.client import BaleiaClient
from baleia_openmetadata.config import BaleiaConfig, ConfigError

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

    def _iter(self, *_: Any, **__: Any) -> Iterable[Either]:
        summary = self.client.summary()
        workspace = summary.get("workspace") or {}
        logger.info(
            "Baleia workspace %s: %s models, %s metrics",
            workspace.get("name") or workspace.get("id"),
            summary.get("models"),
            summary.get("metrics"),
        )
        # Data models, metrics and lineage are added by the following issues.
        yield from ()

    def close(self) -> None:
        self.client.close()


def _without_bi_key(config: WorkflowSource) -> WorkflowSource:
    """A copy of the workflow source whose connection options omit ``biKey``."""
    safe = config.model_copy(deep=True)
    options = safe.serviceConnection.root.config.connectionOptions
    if options is not None and options.root is not None:
        options.root.pop("biKey", None)
    return safe
