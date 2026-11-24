# baleia-openmetadata

An [OpenMetadata](https://open-metadata.org) ingestion connector that discovers
the semantic catalog of [Baleia](https://github.com/maltzsama/baleia): its
semantic models and metrics, with lineage to the physical tables behind them.

> **Status: alpha.** The connector ingests Baleia's semantic models and metrics
> with their lineage. It is tracked in Baleia's epic
> [maltzsama/baleia#1124](https://github.com/maltzsama/baleia/issues/1124).

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
| 0.1.x | 2.0.9 / 2.0.9.0, 2.1.0 / 2.1.0.2 | 3.11, 3.12, 3.13, 3.14 |

The connector is tested against each supported `openmetadata-ingestion`
release and, nightly, against a running server of each release. It needs a
Baleia that serves the semantic catalog routes on its BI gateway (Baleia ADR
0030, contract version 1). Install the connector release that lists your
OpenMetadata version.

The connector runs inside OpenMetadata's ingestion environment, so its Python
range follows OpenMetadata's:

- **3.12** is the reference version: OpenMetadata's official ingestion images
  run it.
- **3.11** is supported until its end of life (2027-10).
- **3.13** and **3.14** are tested by this connector's CI, but not by
  OpenMetadata upstream, which tests 3.10 to 3.12.
- **3.10** is not supported: it reached its end of life on 2026-10-01.

## Installation

The package is published on PyPI as `baleia-openmetadata`. Install it in the
Python environment that runs OpenMetadata's ingestion, usually the
`openmetadata/ingestion` image that matches your server.
[`docker/Dockerfile`](docker/Dockerfile) does that:

```sh
docker build --build-arg OPENMETADATA_VERSION=2.1.0 -t my-ingestion:2.1.0 docker/
```

```dockerfile
ARG OPENMETADATA_VERSION=2.1.0
FROM docker.getcollate.io/openmetadata/ingestion:${OPENMETADATA_VERSION}
USER airflow
RUN pip install --no-cache-dir "baleia-openmetadata==0.1.*"
```

Then run OpenMetadata with that image instead of the stock one, in Docker
Compose or Kubernetes. `scripts/check-image.sh <version>` builds the image from
a local wheel and proves the install: `openmetadata-ingestion` keeps the
image's version and the source class loads.

`openmetadata-ingestion` is intentionally not a runtime dependency. The image
already pins the version that matches the server, and the connector must not
replace it. Outside the image, install `baleia-openmetadata[ingestion]`.

### Run order

1. Ingest the workspace's physical metadata with OpenMetadata's **Trino**
   connector through Baleia's BI gateway (see Baleia's operations guide).
2. Add the **Custom** dashboard service below and run it. Schedule it after the
   Trino service, so the tables lineage points to exist.

## Configuration

In OpenMetadata, add a service under **Dashboard Services → Add New Service →
Custom**, one per Baleia workspace. The service name must not contain `__`,
which separates the parts of metric names. Configure:

- **Source Python Class Name**: `baleia_openmetadata.source.BaleiaSource`
- **Connection Options**:

| Option | Required | Value |
|---|---|---|
| `baleiaUrl` | yes | Origin of Baleia's BI gateway, the same host and port as the Trino connector's (`https://bi.example.com:8443`) |
| `biKeyEmail` | yes | E-mail of the BI key's owner (the Trino connector's username) |
| `biKey` | no | The workspace BI key. Prefer leaving it out and setting `BALEIA_BI_KEY` in the ingestion environment: OpenMetadata stores connection options as plain strings, not as secrets. When the connector registers the service itself (a CLI or YAML run), it omits `biKey`; a value typed in the UI is stored by OpenMetadata as entered |
| `trinoServiceNames` | yes | Comma-separated OpenMetadata database services that ingest the same workspace through the gateway; lineage is resolved against them |
| `allowHttp` | no | `true` to accept a plain `http` URL. Internal networks only: the BI key is a password |
| `verifyTls` | no | `false` to skip certificate verification. Tests only |
| `timeoutSeconds` | no | Request timeout, default `30` |
| `dataModelType` | no | OpenMetadata data model type of Baleia models, default `LookMlView` (see below) |

The BI key's workspace is the service's workspace, and the catalog is what the
key's owner can see in it. One workspace BI key serves both the Trino connector
and this one. Revoking it, or turning BI off for the workspace, stops both.

## What a run creates

| Baleia | OpenMetadata | Name |
|---|---|---|
| Semantic model | `DashboardDataModel` under the service | the model's slug (`<service>.model.<slug>`) |
| Model dimension | data model column, typed from Baleia's logical type | the dimension's name |
| Model metric | data model column (`NUMBER`) and a `Metric` with the SQL Baleia compiles for it | `<service>__<model slug>__<metric name>` |
| Standalone metric | `Metric` with its rendered SQL | `<service>__<metric slug>` |

Names come from slugs, never from labels users edit, so they are stable across
runs, and a run with no change in Baleia changes nothing in OpenMetadata.
`Metric` is a global entity in OpenMetadata, which is why metric names carry the
service name. Labels become display names, and descriptions are copied.

Baleia's logical types map to column types as follows: `boolean` → `BOOLEAN`,
`int64` → `BIGINT`, `float64` → `DOUBLE`, `string` → `STRING`, `date` →
`DATE`, `timestamp` → `TIMESTAMP`, `timestamptz` → `TIMESTAMPZ`, `binary` →
`BINARY`, `json` → `JSON`; any other type becomes `UNKNOWN`, with the Baleia
type kept as the display type.

**Data model type.** OpenMetadata has no Baleia data model type yet. Until it
does, models use `LookMlView`: a LookML view is the closest concept (dimensions
and measures over a table or SQL), and the value exists in every supported
release. Set `dataModelType` to any other value of OpenMetadata's
`DataModelType` to change it.

A model or metric that cannot be mapped is reported as an error in the run
status and the rest of the run continues.

## Lineage

Each run links:

- every physical table a model reads → the model's data model;
- every physical table a standalone metric reads → the metric;
- a model's data model → each metric defined in it.

Baleia names a source table `catalog.schema.table` as the BI gateway's engine
names it, which is how OpenMetadata's Trino connector ingests it through the
gateway. The connector looks it up as `<service>.<catalog>.<schema>.<table>` in
each service of `trinoServiceNames`. A table found in no service, or in more
than one, is reported as a warning and skipped: the connector never guesses
and never creates a table. Run the Trino connector before this one so the
tables exist.

Edges written by this connector are marked with the description `Baleia
semantic catalog`. When Baleia stops reporting a dependency, the next run
removes the marked edge; edges added by anyone else are never touched.

## Deleted items

After a complete read of the catalog, data models of the service and metrics
named `<service>__…` that Baleia no longer reports are **soft-deleted**, like
OpenMetadata's own connectors do. A read that fails deletes nothing. When an
item comes back in Baleia, the next run restores it. Set the pipeline's
`markDeletedDataModels` to `false` to keep everything.

## Limitations

- **Data model type.** OpenMetadata has no Baleia type yet, so data models use
  a borrowed type (`LookMlView` by default). A native type is tracked upstream
  ([maltzsama/baleia#1136](https://github.com/maltzsama/baleia/issues/1136)).
- **What is exposed.** Semantic models and metrics only. Saved queries,
  glossary, certification, owners and tags are not sent in this version.
- **The key owner's view.** The catalog is what the BI key's owner can read in
  the workspace. Content in a space the owner cannot read is not ingested.
- **Lineage needs the Trino tables.** A table missing from the configured
  Trino services is a warning, not a placeholder. Re-run after the Trino
  ingestion.
- **No column-level lineage.** Edges are between tables and entities.
- **Connection options are plain strings** in OpenMetadata. Keep the BI key in
  `BALEIA_BI_KEY`; a key typed in the UI is stored as entered.

## Errors and retries

Requests that fail with HTTP 429, 502, 503 or 504, or that cannot connect, are
retried up to three times with bounded backoff, honoring `Retry-After` in seconds
or as an HTTP date. A page cursor that does not advance stops the run. A refused key, an unsupported
semantic catalog contract version, or a Baleia without the semantic catalog
routes fails the run with an explicit message, which never includes the key.

## Development

```sh
uv venv
uv pip install -e ".[ingestion]" --group test --group lint
uv run --no-sync pytest
uv run --no-sync ruff check . && uv run --no-sync ruff format --check .
```

### Integration suite

`tests/integration` runs the connector against a real OpenMetadata server: it
creates a Trino table standing in for the Trino connector's, serves a recorded
semantic catalog from a local stand-in for Baleia's gateway, and runs the
ingestion workflow three times (full catalog, items removed, items back),
checking the data models, metrics, lineage, stale edges and soft deletes
through OpenMetadata's API. It is skipped unless `OPENMETADATA_URL` is set.

```sh
export OPENMETADATA_URL="$(scripts/openmetadata.sh up 2.1.0)"   # or 2.0.9
uv pip install "openmetadata-ingestion==2.1.0.2"                # match the server
uv run --no-sync pytest tests/integration -v
scripts/openmetadata.sh down 2.1.0
```

The `Integration` workflow runs it nightly and on demand against every
supported release. The end-to-end check against a real Baleia lives in
Baleia's repository.

See [AGENTS.md](AGENTS.md) for the contribution workflow.

## Releasing

release-please keeps a release pull request open with the next version and the
changelog built from conventional commits on `main`. Merging it tags the
release, creates the GitHub release and publishes the wheel and the sdist to
PyPI through **Trusted Publishing** (OIDC, workflow `release.yml`, environment
`pypi`). No PyPI token is stored in this repository.

A version on PyPI can never be replaced, only yanked. Before merging a release
pull request, check that the `Integration` workflow is green on `main` for every
supported OpenMetadata release.

## License

Apache License 2.0. See [LICENSE](LICENSE).
