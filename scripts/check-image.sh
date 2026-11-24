#!/usr/bin/env bash
# Builds the connector wheel, installs it into OpenMetadata's official ingestion
# image with docker/Dockerfile, and checks that the image's
# openmetadata-ingestion version did not change and that the source loads.
#
#   scripts/check-image.sh 2.1.0
set -euo pipefail

version="${1:?usage: $0 OPENMETADATA_VERSION}"
root="$(cd "$(dirname "$0")/.." && pwd)"
base="docker.getcollate.io/openmetadata/ingestion:$version"
tag="baleia-openmetadata-check:$version"
context="$(mktemp -d)"
trap 'rm -rf "$context"; docker image rm -f "$tag" >/dev/null 2>&1 || true' EXIT

before="$(docker run --rm --entrypoint python "$base" -c 'import importlib.metadata as m; print(m.version("openmetadata-ingestion"))')"
(cd "$root" && uv build --wheel -q -o "$context")
wheel="$(basename "$(ls "$context"/*.whl)")"
cp "$root/docker/Dockerfile" "$context/Dockerfile"
# The wheel is copied into the build context and installed from there.
sed -i "s|^RUN pip install|COPY $wheel /tmp/$wheel\nRUN pip install|" "$context/Dockerfile"
docker build -q --build-arg "OPENMETADATA_VERSION=$version" --build-arg "BALEIA_OPENMETADATA=/tmp/$wheel" -t "$tag" "$context" >/dev/null

after="$(docker run --rm --entrypoint python "$tag" -c '
import importlib.metadata as m
from baleia_openmetadata.source import BaleiaSource  # noqa: F401
print(m.version("openmetadata-ingestion"))')"
if [[ "$before" != "$after" ]]; then
  echo "check-image: installing the connector changed openmetadata-ingestion from $before to $after" >&2
  exit 1
fi
echo "check-image: $wheel installs into $base; openmetadata-ingestion stays $after and BaleiaSource loads"
