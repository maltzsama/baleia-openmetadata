# OpenMetadata's ingestion image with the Baleia connector installed.
#
#   docker build --build-arg OPENMETADATA_VERSION=2.1.0 -t my-ingestion:2.1.0 docker/
#
# Use the tag that matches your OpenMetadata server. The connector does not
# change the image's openmetadata-ingestion: it declares no dependency on it.
ARG OPENMETADATA_VERSION=2.1.0
FROM docker.getcollate.io/openmetadata/ingestion:${OPENMETADATA_VERSION}

# A released version from PyPI, or a local wheel path for an unreleased build.
ARG BALEIA_OPENMETADATA=baleia-openmetadata
USER airflow
RUN pip install --no-cache-dir "${BALEIA_OPENMETADATA}"
