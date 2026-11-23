# baleia-openmetadata

An [OpenMetadata](https://open-metadata.org) ingestion connector that discovers
the semantic catalog of [Baleia](https://github.com/maltzsama/baleia): its
semantic models and metrics, with lineage to the physical tables behind them.

> **Status: pre-alpha.** This repository is being bootstrapped. The connector
> is not functional yet; the work is tracked in this repository's issues and in
> Baleia's epic [maltzsama/baleia#1124](https://github.com/maltzsama/baleia/issues/1124).

## Why a dedicated connector

OpenMetadata finds a source only through an ingestion connector that runs
inside its ingestion framework. Baleia already reaches OpenMetadata in two ways,
and neither carries its semantic layer:

- The stock **Trino** connector, pointed at Baleia's workspace-scoped BI
  gateway, ingests the physical side: catalogs, schemas, tables, columns and
  views. Semantic models and metrics are not Trino objects, so it cannot see
  them.
- **OpenLineage** only describes jobs and datasets. OpenMetadata turns them
  into pipelines or tables, never into the data models and metrics a semantic
  layer is made of.

OpenMetadata represents semantic layers (Looker views and explores, Tableau
data sources, Power BI datasets, Superset datasets...) as **data models** under a
dashboard service, and business metrics as **metrics**. It supports custom
connectors for dashboard services, and this package is that connector for
Baleia.

The responsibility sits on the OpenMetadata side: OpenMetadata pulls from
Baleia on its own schedule, as it does for any other source. Baleia stores no
OpenMetadata credentials and never calls OpenMetadata.

## How it works

```
Baleia                                   OpenMetadata
┌──────────────────────────┐             ┌───────────────────────────────────┐
│ BI gateway (Trino proto) │◀── Trino ───│ Trino connector  → tables, views  │
│ Semantic catalog API     │◀── HTTP ────│ baleia-openmetadata               │
└──────────────────────────┘   BI key    │   → data models, metrics, lineage │
                                         └───────────────────────────────────┘
```

For each Baleia workspace, the connector reads the semantic catalog API with the
workspace's **BI key**, the same credential the Trino connector uses, and
creates:

| Baleia | OpenMetadata |
|---|---|
| Workspace | Dashboard service (`CustomDashboard`) |
| Semantic model | `DashboardDataModel`: columns from dimensions and measures, SQL, link back to Baleia |
| Metric | `Metric`: description and SQL expression |
| Model or metric dependencies | Lineage from the tables ingested by the Trino connector |
| Deleted model or metric | Soft-deleted on the next run |

Until OpenMetadata ships a `Baleia` service type and data model type upstream,
the connector uses the `CustomDashboard` service type and an existing data model
type.

## Compatibility

| baleia-openmetadata | OpenMetadata / `openmetadata-ingestion` | Python |
|---|---|---|
| unreleased | 2.0.x, 2.1.x | 3.10, 3.11 |

The connector is tested against each supported `openmetadata-ingestion`
release. Install the connector release that lists your OpenMetadata version.

## Installation

The package is published on PyPI as `baleia-openmetadata`. It must be installed
in the Python environment that runs OpenMetadata's ingestion, usually the
`openmetadata/ingestion` image that matches your server version:

```dockerfile
FROM openmetadata/ingestion:2.1.0.2
USER airflow
RUN pip install --no-cache-dir "baleia-openmetadata==<version>"
```

`openmetadata-ingestion` is intentionally not a runtime dependency. The image
already pins the version that matches the server, and the connector must not
replace it. Outside the image, install `baleia-openmetadata[ingestion]`.

Then, in OpenMetadata, add a service under **Dashboard Services → Add New
Service → Custom** and set the source Python class name documented in the first
release.

## Development

```sh
uv venv
uv pip install -e ".[ingestion]" --group test --group lint
uv run --no-sync pytest
uv run --no-sync ruff check . && uv run --no-sync ruff format --check .
```

See [AGENTS.md](AGENTS.md) for the contribution workflow.

## Releasing

Releases are cut by release-please from conventional commits on `main` after CI
passes, and published to PyPI through **Trusted Publishing** (OIDC). No PyPI
token is stored in this repository.

## License

Apache License 2.0. See [LICENSE](LICENSE).
