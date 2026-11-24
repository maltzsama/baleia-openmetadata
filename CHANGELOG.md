# Changelog

## 0.1.0 (2026-11-24)


### Features

* **client:** read Baleia's semantic catalog routes ([df47088](https://github.com/maltzsama/baleia-openmetadata/commit/df4708810f7a7a3df23d319e86657b26403c7455))
* **config:** validate the Baleia connection options ([4044f90](https://github.com/maltzsama/baleia-openmetadata/commit/4044f904f502b6d40bcbb9e64ab940519d766362))
* **entities:** map Baleia models and metrics to OpenMetadata requests ([702108f](https://github.com/maltzsama/baleia-openmetadata/commit/702108fd74eacedfbbf83254143ed03588d04e9b))
* **lineage:** resolve Baleia source tables and mark owned edges ([534702b](https://github.com/maltzsama/baleia-openmetadata/commit/534702b3cf0c0a8cb6ef47197bfd379c9cc71df7))
* **source:** ingest data models and metrics ([34e274e](https://github.com/maltzsama/baleia-openmetadata/commit/34e274e6e866b908294feacbc609c9f196d1d5c5))
* **source:** link the catalog to its tables and soft-delete removed items ([28961c8](https://github.com/maltzsama/baleia-openmetadata/commit/28961c821086881b09ff08548c87edd9d0e58a4d))
* **source:** register the Baleia custom dashboard source ([a358c5c](https://github.com/maltzsama/baleia-openmetadata/commit/a358c5c6f283a50b9af54d82c77ae0b003de8017))


### Bug Fixes

* **ci:** drop end-of-life Python 3.10 and test 3.11 to 3.14 ([1e7d048](https://github.com/maltzsama/baleia-openmetadata/commit/1e7d048c75d06ecfc57d02a4a055bb1301ea1238))
* **ci:** pin setup-uv to a released version tag ([25380d8](https://github.com/maltzsama/baleia-openmetadata/commit/25380d8512874a118ef1e4b5ee475b7cdf8a4a8a))
* **ci:** test on Python 3.12, the version in OpenMetadata's images ([2a24f27](https://github.com/maltzsama/baleia-openmetadata/commit/2a24f27d0f6d5e749543a8f2d2f8c065e5a7d96c))
* **lineage:** forget deleted edges in the OpenMetadata client cache ([9bd6b6e](https://github.com/maltzsama/baleia-openmetadata/commit/9bd6b6ee314fef097622a7ff55d7ec864411dc2d))


### Documentation

* prepare the README for the first release ([0fdcfd4](https://github.com/maltzsama/baleia-openmetadata/commit/0fdcfd4a976427f4b7d2c4bccb8d31688155c9eb))


### Miscellaneous

* bootstrap the connector repository ([1382917](https://github.com/maltzsama/baleia-openmetadata/commit/1382917e131d4c2071ed548ae496258dc2a3a6d3))
* disable the OpenMetadata 2.0 pytest plugin ([309b951](https://github.com/maltzsama/baleia-openmetadata/commit/309b9517759db965c95e2485c9532559be99eb52))
* **integration:** run the connector against real OpenMetadata servers ([994a1c7](https://github.com/maltzsama/baleia-openmetadata/commit/994a1c7106ffb32918298dd8156fbc78b8d7761a))
