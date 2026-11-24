"""Fixtures of the integration suite: a running OpenMetadata server.

The suite runs only when OPENMETADATA_URL points at a server, for example one
started by ``scripts/openmetadata.sh up 2.1.0``. It logs in with the
quickstart's default admin unless OPENMETADATA_ADMIN_EMAIL and
OPENMETADATA_ADMIN_PASSWORD say otherwise.
"""

from __future__ import annotations

import base64
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
import requests


@dataclass
class OpenMetadataServer:
    url: str
    token: str

    @property
    def api(self) -> str:
        return f"{self.url}/api/v1"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def get(self, path: str, **params: Any) -> Any:
        response = requests.get(
            f"{self.api}{path}", headers=self._headers(), params=params, timeout=30
        )
        response.raise_for_status()
        return response.json()

    def put(self, path: str, body: dict[str, Any]) -> Any:
        response = requests.put(f"{self.api}{path}", headers=self._headers(), json=body, timeout=30)
        response.raise_for_status()
        return response.json()

    def delete(self, path: str, **params: Any) -> None:
        response = requests.delete(
            f"{self.api}{path}", headers=self._headers(), params=params, timeout=60
        )
        if response.status_code not in (200, 404):
            response.raise_for_status()


@pytest.fixture(scope="session")
def openmetadata() -> OpenMetadataServer:
    url = os.environ.get("OPENMETADATA_URL", "").rstrip("/")
    if not url:
        pytest.skip("OPENMETADATA_URL is not set; start a server with scripts/openmetadata.sh")
    email = os.environ.get("OPENMETADATA_ADMIN_EMAIL", "admin@open-metadata.org")
    password = os.environ.get("OPENMETADATA_ADMIN_PASSWORD", "admin")
    response = requests.post(
        f"{url}/api/v1/users/login",
        json={"email": email, "password": base64.b64encode(password.encode()).decode()},
        timeout=30,
    )
    response.raise_for_status()
    return OpenMetadataServer(url=url, token=response.json()["accessToken"])


@pytest.fixture
def names() -> Iterator[dict[str, str]]:
    """Unique service names, so runs never collide on a shared server."""
    suffix = uuid.uuid4().hex[:8]
    yield {"dashboard": f"baleia-it-{suffix}", "trino": f"trino-it-{suffix}"}


@pytest.fixture
def trino_orders(openmetadata: OpenMetadataServer, names: dict[str, str]) -> Iterator[str]:
    """The table OpenMetadata's Trino connector would ingest through the gateway."""
    service = names["trino"]
    openmetadata.put(
        "/services/databaseServices",
        {
            "name": service,
            "serviceType": "Trino",
            "connection": {
                "config": {"type": "Trino", "hostPort": "localhost:1", "username": "it"}
            },
        },
    )
    openmetadata.put("/databases", {"name": "e2e_tpch", "service": service})
    openmetadata.put("/databaseSchemas", {"name": "tiny", "database": f"{service}.e2e_tpch"})
    table = openmetadata.put(
        "/tables",
        {
            "name": "orders",
            "databaseSchema": f"{service}.e2e_tpch.tiny",
            "columns": [{"name": "orderkey", "dataType": "BIGINT"}],
        },
    )
    yield table["fullyQualifiedName"]
    service_id = openmetadata.get(f"/services/databaseServices/name/{service}")["id"]
    openmetadata.delete(
        f"/services/databaseServices/{service_id}", recursive="true", hardDelete="true"
    )
