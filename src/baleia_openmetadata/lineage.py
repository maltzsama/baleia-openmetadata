"""Lineage from Baleia's physical tables to its semantic entities.

Baleia names a source table ``catalog.schema.table`` as its BI gateway's
engine names it, which is how OpenMetadata's Trino connector ingests it through
the gateway: ``<trino service>.<catalog>.<schema>.<table>``. A table is linked
only when it resolves in exactly one configured Trino service; otherwise it is
reported and skipped, never guessed and never created.

Every edge this connector writes carries :data:`EDGE_DESCRIPTION`, so a later
run can remove the edges it owns that Baleia no longer reports, without
touching edges written by anyone else.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from metadata.generated.schema.api.lineage.addLineage import AddLineageRequest
from metadata.generated.schema.entity.data.table import Table
from metadata.generated.schema.type.entityLineage import EntitiesEdge, LineageDetails
from metadata.generated.schema.type.entityLineage import Source as LineageSource
from metadata.generated.schema.type.entityReference import EntityReference
from metadata.ingestion.ometa.ometa_api import OpenMetadata
from metadata.utils import fqn

# The marker of the edges this connector owns.
EDGE_DESCRIPTION = "Baleia semantic catalog"


@dataclass(frozen=True)
class Resolution:
    """The OpenMetadata table a Baleia source table names, or why there is none."""

    table: Table | None
    problem: str | None = None


class TableResolver:
    """Resolves Baleia source tables against the configured Trino services."""

    def __init__(self, metadata: OpenMetadata, services: Sequence[str]) -> None:
        self._metadata = metadata
        self._services = tuple(services)
        self._cache: dict[str, Resolution] = {}

    def resolve(self, source_table: str) -> Resolution:
        if source_table not in self._cache:
            self._cache[source_table] = self._resolve(source_table)
        return self._cache[source_table]

    def _resolve(self, source_table: str) -> Resolution:
        parts = source_table.split(".")
        if len(parts) < 3 or not all(parts):
            return Resolution(None, f"{source_table!r} is not catalog.schema.table")
        catalog, schema, name = parts[0], ".".join(parts[1:-1]), parts[-1]
        hits: list[tuple[str, Table]] = []
        for service in self._services:
            table = self._metadata.get_by_name(
                entity=Table, fqn=fqn._build(service, catalog, schema, name)
            )
            if table is not None:
                hits.append((service, table))
        if not hits:
            return Resolution(None, f"{source_table} is not a table of {', '.join(self._services)}")
        if len(hits) > 1:
            found = ", ".join(service for service, _ in hits)
            return Resolution(None, f"{source_table} is ambiguous: it exists in {found}")
        return Resolution(hits[0][1])


def edge_request(from_id: Any, from_type: str, to_id: Any, to_type: str) -> AddLineageRequest:
    """One lineage edge owned by this connector."""
    return AddLineageRequest(
        edge=EntitiesEdge(
            fromEntity=EntityReference(id=from_id, type=from_type),
            toEntity=EntityReference(id=to_id, type=to_type),
            lineageDetails=LineageDetails(
                source=LineageSource.DashboardLineage,
                description=EDGE_DESCRIPTION,
            ),
        )
    )


def stale_edges(
    lineage: dict[str, Any] | None, target_id: str, wanted_upstream: Iterable[str]
) -> list[dict[str, Any]]:
    """The edges into ``target_id`` that this connector owns but no longer wants.

    ``lineage`` is OpenMetadata's lineage response for the target.
    """
    wanted = {str(i) for i in wanted_upstream}
    out = []
    for edge in (lineage or {}).get("upstreamEdges") or []:
        details = edge.get("lineageDetails") or {}
        if str(edge.get("toEntity")) != str(target_id):
            continue
        if details.get("description") != EDGE_DESCRIPTION:
            continue
        if str(edge.get("fromEntity")) in wanted:
            continue
        out.append(edge)
    return out


def forget_edge(metadata: OpenMetadata, from_ref: EntityReference, to_ref: EntityReference) -> None:
    """Drops a deleted edge from the OpenMetadata client's edge cache.

    ``add_lineage`` looks edges up through a cache that ``delete_lineage_edge``
    does not invalidate: per client in 2.1, per process in 2.0. Without this, an
    edge deleted and added again in the same process would be patched instead
    of created, and stay deleted. Best effort: the cache is an implementation
    detail, found by capability rather than by version.
    """
    try:
        key = metadata._lineage_edge_cache_key(from_ref, to_ref)
    except Exception:
        return
    caches = [getattr(metadata, "_lineage_edge_cache", None)]
    try:
        from metadata.ingestion.ometa.mixins import lineage_mixin

        caches.append(getattr(lineage_mixin, "search_cache", None))
    except ImportError:
        pass
    for cache in caches:
        store = getattr(cache, "_cache", None)
        if isinstance(store, dict):
            store.pop(key, None)
