"""OpenMetadata source for Baleia's semantic catalog.

Register it under Dashboard Services > Custom with the source Python class
``baleia_openmetadata.source.BaleiaSource``.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable, Iterable
from typing import Any

from metadata.generated.schema.entity.data.dashboardDataModel import (
    DashboardDataModel,
    DataModelType,
)
from metadata.generated.schema.entity.data.metric import Metric
from metadata.generated.schema.entity.services.connections.dashboard import (
    customDashboardConnection,
)
from metadata.generated.schema.entity.services.dashboardService import DashboardService
from metadata.generated.schema.entity.services.ingestionPipelines.status import StackTraceError
from metadata.generated.schema.metadataIngestion.workflow import Source as WorkflowSource
from metadata.generated.schema.type.entityLineage import EntitiesEdge
from metadata.generated.schema.type.entityReference import EntityReference
from metadata.ingestion.api.models import Either
from metadata.ingestion.api.steps import InvalidSourceException, Source
from metadata.ingestion.models.barrier import Barrier
from metadata.ingestion.models.delete_entity import DeleteEntity
from metadata.ingestion.ometa.ometa_api import OpenMetadata
from metadata.utils import fqn
from metadata.utils.logger import ingestion_logger

from baleia_openmetadata.client import BaleiaClient
from baleia_openmetadata.config import BaleiaConfig, ConfigError
from baleia_openmetadata.entities import (
    NAME_SEPARATOR,
    data_model_request,
    metric_name,
    metric_request,
    model_metric_requests,
)
from baleia_openmetadata.lineage import TableResolver, edge_request, stale_edges

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
        if NAME_SEPARATOR in config.serviceName:
            # Metric names are <service>__<…>, and deletion recognizes a
            # service's metrics by that prefix: "sales" must never match
            # the metrics of a service named "sales__eu".
            raise InvalidSourceException(
                f"The service name must not contain {NAME_SEPARATOR!r}: got {config.serviceName!r}"
            )
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

    @property
    def mark_deleted(self) -> bool:
        """Whether entities Baleia no longer reports are soft-deleted."""
        source_config = self.config.sourceConfig.config
        return bool(getattr(source_config, "markDeletedDataModels", True))

    def _iter(self, *_: Any, **__: Any) -> Iterable[Either]:
        summary = self.client.summary()
        workspace = summary.get("workspace") or {}
        project = workspace.get("name") or workspace.get("id")
        # The whole catalog is read before anything is written: a failed read
        # stops the run before any deletion.
        models = list(self.client.models())
        metrics = list(self.client.metrics())
        logger.info(
            "Baleia workspace %s: %d models, %d metrics", project, len(models), len(metrics)
        )

        service = self.service_name
        model_names: set[str] = set()
        metric_names: set[str] = set()
        for model in models:
            built = _either(
                f"data model {model.get('slug')}",
                lambda m=model: data_model_request(m, service, self.data_model_type, project),
            )
            if built.right is not None:
                model_names.add(built.right.name.root)
            yield built
            try:
                metric_requests = model_metric_requests(model, service)
            except Exception as err:
                yield _failure(f"metrics of model {model.get('slug')}", err)
                continue
            for request in metric_requests:
                metric_names.add(request.name.root)
                yield Either(right=request)
        for metric in metrics:
            built = _either(
                f"metric {metric.get('slug')}", lambda m=metric: metric_request(m, service)
            )
            if built.right is not None:
                metric_names.add(built.right.name.root)
            yield built

        # Data models are written in bulk: flush them so lineage can find them.
        yield Either(right=Barrier(reason="Baleia data models before lineage"))
        yield from self._lineage(models, metrics)
        if self.mark_deleted:
            yield from self._soft_delete(model_names, metric_names)

    def _lineage(
        self, models: list[dict[str, Any]], metrics: list[dict[str, Any]]
    ) -> Iterable[Either]:
        service = self.service_name
        tables = TableResolver(self.metadata, self.baleia.trino_services)
        for model in models:
            slug = model.get("slug")
            if not slug:
                continue
            data_model = self.metadata.get_by_name(
                entity=DashboardDataModel, fqn=fqn._build(service, "model", slug)
            )
            if data_model is None:
                self.status.warning(
                    f"data model {slug}", "not found after ingestion; lineage skipped"
                )
                continue
            upstream = self._resolve_tables(
                f"data model {slug}", model.get("source_tables"), tables
            )
            yield from self._link(upstream, data_model.id, "dashboardDataModel")
            for metric in model.get("metrics") or []:
                entity = self.metadata.get_by_name(
                    entity=Metric, fqn=metric_name(service, slug, metric["name"])
                )
                if entity is not None:
                    yield from self._link(
                        [data_model.id], entity.id, "metric", "dashboardDataModel"
                    )
        for metric in metrics:
            slug = metric.get("slug")
            if not slug:
                continue
            entity = self.metadata.get_by_name(entity=Metric, fqn=metric_name(service, slug))
            if entity is None:
                self.status.warning(f"metric {slug}", "not found after ingestion; lineage skipped")
                continue
            upstream = self._resolve_tables(f"metric {slug}", metric.get("source_tables"), tables)
            yield from self._link(upstream, entity.id, "metric")

    def _resolve_tables(self, owner: str, source_tables: Any, tables: TableResolver) -> list[Any]:
        ids = []
        for source_table in source_tables or []:
            resolution = tables.resolve(source_table)
            if resolution.table is None:
                self.status.warning(owner, f"lineage skipped: {resolution.problem}")
                continue
            ids.append(resolution.table.id)
        return ids

    def _link(
        self,
        upstream_ids: list[Any],
        target_id: Any,
        target_type: str,
        upstream_type: str = "table",
    ) -> Iterable[Either]:
        """Adds the wanted edges into the target and removes the stale ones it owns."""
        target = str(target_id.root if hasattr(target_id, "root") else target_id)
        wanted = [str(i.root if hasattr(i, "root") else i) for i in upstream_ids]
        lineage = self.metadata.get_lineage_by_id(
            entity=target_type, entity_id=target, up_depth=1, down_depth=0
        )
        for edge in stale_edges(lineage, target, wanted):
            try:
                self.metadata.delete_lineage_edge(
                    edge=EntitiesEdge(
                        fromEntity=_reference(lineage, edge["fromEntity"]),
                        toEntity=EntityReference(id=target, type=target_type),
                    )
                )
            except Exception as err:
                yield _failure(f"stale lineage edge into {target_type} {target}", err)
        for upstream in wanted:
            yield Either(right=edge_request(upstream, upstream_type, target, target_type))

    def _soft_delete(self, model_names: set[str], metric_names: set[str]) -> Iterable[Either]:
        service = self.service_name
        for data_model in self.metadata.list_all_entities(
            entity=DashboardDataModel, params={"service": service}
        ):
            if data_model.name.root not in model_names:
                yield Either(right=DeleteEntity(entity=data_model))
        prefix = metric_name(service, "")
        for metric in self.metadata.list_all_entities(entity=Metric):
            name = metric.name.root
            if name.startswith(prefix) and name not in metric_names:
                yield Either(right=DeleteEntity(entity=metric))

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


def _reference(lineage: dict[str, Any] | None, entity_id: Any) -> EntityReference:
    """The reference of an upstream node of a lineage response, with its type."""
    for node in (lineage or {}).get("nodes") or []:
        if str(node.get("id")) == str(entity_id):
            return EntityReference(id=str(entity_id), type=node.get("type") or "table")
    return EntityReference(id=str(entity_id), type="table")
