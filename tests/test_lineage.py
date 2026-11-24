from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from metadata.generated.schema.type.entityLineage import Source as LineageSource

from baleia_openmetadata.lineage import EDGE_DESCRIPTION, TableResolver, edge_request, stale_edges

ORDERS = SimpleNamespace(id="t-orders")


def metadata_with(tables: dict[str, object]) -> MagicMock:
    metadata = MagicMock()
    metadata.get_by_name.side_effect = lambda entity, fqn: tables.get(fqn)
    return metadata


def test_resolves_in_one_service() -> None:
    resolver = TableResolver(
        metadata_with({"trino-a.lake.sales.orders": ORDERS}), ["trino-a", "trino-b"]
    )
    assert resolver.resolve("lake.sales.orders").table is ORDERS


def test_missing_ambiguous_and_malformed() -> None:
    tables = {"a.lake.s.t": ORDERS, "b.lake.s.t": SimpleNamespace(id="other")}
    resolver = TableResolver(metadata_with(tables), ["a", "b"])
    ambiguous = resolver.resolve("lake.s.t")
    assert ambiguous.table is None and "ambiguous" in ambiguous.problem
    missing = resolver.resolve("lake.s.nope")
    assert missing.table is None and "is not a table of a, b" in missing.problem
    malformed = resolver.resolve("orders")
    assert malformed.table is None and "catalog.schema.table" in malformed.problem


def test_resolution_is_cached() -> None:
    metadata = metadata_with({"svc.lake.sales.orders": ORDERS})
    resolver = TableResolver(metadata, ["svc"])
    resolver.resolve("lake.sales.orders")
    resolver.resolve("lake.sales.orders")
    assert metadata.get_by_name.call_count == 1


def test_edge_request_is_marked() -> None:
    req = edge_request(
        "a8a6d9f0-1111-4b3c-9d1e-000000000001",
        "table",
        "a8a6d9f0-1111-4b3c-9d1e-000000000002",
        "metric",
    )
    details = req.edge.lineageDetails
    assert details.description == EDGE_DESCRIPTION
    assert details.source is LineageSource.DashboardLineage
    assert req.edge.toEntity.type == "metric"


def test_stale_edges_only_touch_owned_edges() -> None:
    lineage = {
        "upstreamEdges": [
            {
                "fromEntity": "keep",
                "toEntity": "t",
                "lineageDetails": {"description": EDGE_DESCRIPTION},
            },
            {
                "fromEntity": "gone",
                "toEntity": "t",
                "lineageDetails": {"description": EDGE_DESCRIPTION},
            },
            {
                "fromEntity": "manual",
                "toEntity": "t",
                "lineageDetails": {"description": "added by hand"},
            },
            {
                "fromEntity": "gone",
                "toEntity": "other",
                "lineageDetails": {"description": EDGE_DESCRIPTION},
            },
        ]
    }
    assert [e["fromEntity"] for e in stale_edges(lineage, "t", ["keep"])] == ["gone"]
    assert stale_edges(None, "t", []) == []


def test_forget_edge_clears_client_and_module_caches(monkeypatch) -> None:
    from collections import OrderedDict

    from metadata.generated.schema.type.entityReference import EntityReference

    from baleia_openmetadata.lineage import forget_edge

    class Cache:
        def __init__(self) -> None:
            self._cache = OrderedDict({"k": 1, "other": 2})

    client_cache, module_cache = Cache(), Cache()
    metadata = MagicMock()
    metadata._lineage_edge_cache_key.return_value = "k"
    metadata._lineage_edge_cache = client_cache
    from metadata.ingestion.ometa.mixins import lineage_mixin

    monkeypatch.setattr(lineage_mixin, "search_cache", module_cache, raising=False)
    ref = EntityReference(id="a8a6d9f0-1111-4b3c-9d1e-000000000001", type="table")
    forget_edge(metadata, ref, ref)
    assert list(client_cache._cache) == ["other"]
    assert list(module_cache._cache) == ["other"]


def test_forget_edge_without_a_cache_is_harmless() -> None:
    from metadata.generated.schema.type.entityReference import EntityReference

    from baleia_openmetadata.lineage import forget_edge

    metadata = MagicMock()
    metadata._lineage_edge_cache_key.side_effect = AttributeError
    ref = EntityReference(id="a8a6d9f0-1111-4b3c-9d1e-000000000001", type="table")
    forget_edge(metadata, ref, ref)
