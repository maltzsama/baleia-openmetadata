#!/usr/bin/env bash
# Starts or stops a pinned OpenMetadata quickstart for the integration suite.
#
#   scripts/openmetadata.sh up 2.1.0     # prints the server URL when healthy
#   scripts/openmetadata.sh down 2.1.0
#
# Each release is pinned by the SHA-256 of its quickstart compose file. Ports
# are bound to loopback only; OPENMETADATA_PORT (default 8585) and
# OPENMETADATA_ADMIN_PORT (default 8586) choose them.
set -euo pipefail

action="${1:?usage: $0 up|down VERSION}"
version="${2:?usage: $0 up|down VERSION}"
case "$version" in
  2.0.9) sha256=54dbae6828e1dddb9fd2fcccc868121d353d518ded64b47e75828d43ca64034f ;;
  2.1.0) sha256=34b145e3a682ef10f43513f4436b4373b99889a96caf6480277f27889d0bf9c9 ;;
  *) echo "openmetadata.sh: OpenMetadata $version is not pinned" >&2; exit 1 ;;
esac
port="${OPENMETADATA_PORT:-8585}"
admin_port="${OPENMETADATA_ADMIN_PORT:-8586}"
project="baleia-om-it-${version//./-}"
workdir="${OPENMETADATA_WORKDIR:-${TMPDIR:-/tmp}/$project}"
mkdir -p "$workdir"
compose="$workdir/docker-compose.yml"
override="$workdir/docker-compose.override.yml"
args=(-p "$project" -f "$compose" -f "$override")

if [[ "$action" == down ]]; then
  if [[ -f "$compose" ]]; then
    docker compose "${args[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  # The quickstart bind-mounts MySQL data as root; remove it from a container.
  if [[ -d "$workdir/docker-volume" ]]; then
    docker run --rm -v "$workdir/docker-volume:/cleanup" alpine:3.20 find /cleanup -mindepth 1 -delete >/dev/null 2>&1 || true
  fi
  rm -rf "$workdir"
  exit 0
fi

curl -fsSL -o "$compose" \
  "https://raw.githubusercontent.com/open-metadata/OpenMetadata/${version}-release/docker/docker-compose-quickstart/docker-compose.yml"
actual="$(sha256sum "$compose" | cut -d ' ' -f1)"
if [[ "$actual" != "$sha256" ]]; then
  echo "openmetadata.sh: compose checksum mismatch for $version: got $actual" >&2
  exit 1
fi
cat >"$override" <<YAML
services:
  mysql:
    container_name: !reset null
    ports: !override []
  elasticsearch:
    container_name: !reset null
    ports: !override []
  execute-migrate-all:
    container_name: !reset null
  openmetadata-server:
    container_name: !reset null
    ports: !override
      - "127.0.0.1:$port:8585"
      - "127.0.0.1:$admin_port:8586"
  ingestion:
    container_name: !reset null
    ports: !override []
networks:
  app_net:
    ipam: !reset {}
YAML
# The ingestion container is not needed: the suite runs the workflow in process.
docker compose "${args[@]}" up -d mysql elasticsearch execute-migrate-all openmetadata-server >&2
for _ in $(seq 1 180); do
  if curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:$admin_port/healthcheck"; then
    echo "http://127.0.0.1:$port"
    exit 0
  fi
  sleep 2
done
echo "openmetadata.sh: OpenMetadata $version did not become healthy" >&2
docker compose "${args[@]}" logs --tail=100 openmetadata-server >&2 || true
exit 1
