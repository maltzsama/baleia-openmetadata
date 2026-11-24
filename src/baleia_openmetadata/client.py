"""Client for Baleia's semantic catalog routes.

The routes live on Baleia's BI gateway (Baleia ADR 0030) and authenticate with
HTTP Basic: the BI key owner's e-mail and the BI key. The key is never logged
and never part of an exception message.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import requests
from metadata.utils.logger import ingestion_logger

from baleia_openmetadata.config import BaleiaConfig

logger = ingestion_logger()

# The contract version this client understands. Baleia changes it only on an
# incompatible change.
SUPPORTED_CONTRACT_VERSION = 1

PAGE_SIZE = 500
MAX_ATTEMPTS = 3
MAX_RETRY_DELAY_SECONDS = 10.0
RETRYABLE_STATUS = frozenset({429, 502, 503, 504})

SUMMARY_PATH = "/baleia/v1/semantic"
MODELS_PATH = "/baleia/v1/semantic/models"
METRICS_PATH = "/baleia/v1/semantic/metrics"


class BaleiaError(Exception):
    """A request to Baleia failed."""


class BaleiaAuthError(BaleiaError):
    """Baleia refused the BI key, or BI is disabled for the key's workspace."""


class BaleiaContractError(BaleiaError):
    """Baleia speaks a contract version this connector does not support."""


class BaleiaClient:
    """Reads one workspace's semantic catalog: the BI key's workspace."""

    def __init__(
        self,
        config: BaleiaConfig,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._config = config
        self._session = session or requests.Session()
        self._session.auth = (config.email, config.bi_key)
        self._session.headers["Accept"] = "application/json"
        self._session.headers["User-Agent"] = "baleia-openmetadata"
        self._sleep = sleep
        self._now = now

    def close(self) -> None:
        self._session.close()

    def summary(self) -> dict[str, Any]:
        """Returns the workspace and the model and metric counts."""
        return self._get(SUMMARY_PATH)

    def models(self) -> Iterator[dict[str, Any]]:
        """Yields every semantic model, following the pages."""
        yield from self._pages(MODELS_PATH)

    def metrics(self) -> Iterator[dict[str, Any]]:
        """Yields every standalone metric, following the pages."""
        yield from self._pages(METRICS_PATH)

    def _pages(self, path: str) -> Iterator[dict[str, Any]]:
        after = ""
        seen: set[str] = set()
        while True:
            params: dict[str, Any] = {"limit": PAGE_SIZE}
            if after:
                params["after"] = after
            page = self._get(path, params)
            items = page.get("items")
            if not isinstance(items, list):
                raise BaleiaError(f"{path} returned no item list")
            yield from items
            after = page.get("next_after") or ""
            if not after:
                return
            # A cursor that does not advance would page forever.
            if after in seen:
                raise BaleiaError(f"{path} returned a repeated page cursor")
            seen.add(after)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self._config.url + path
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self._session.get(
                    url,
                    params=params,
                    timeout=self._config.timeout_seconds,
                    verify=self._config.verify_tls,
                    allow_redirects=False,
                )
            except requests.RequestException as err:
                if attempt == MAX_ATTEMPTS:
                    raise BaleiaError(
                        f"Baleia is unreachable at {self._config.url}: {type(err).__name__}"
                    ) from None
                self._backoff(attempt, None)
                continue

            if response.status_code in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS:
                self._backoff(attempt, response.headers.get("Retry-After"))
                continue
            return self._decode(path, response)
        raise BaleiaError(f"{path} failed after {MAX_ATTEMPTS} attempts")  # pragma: no cover

    def _decode(self, path: str, response: requests.Response) -> dict[str, Any]:
        status = response.status_code
        if status in {401, 403}:
            raise BaleiaAuthError(
                f"Baleia refused the BI key (HTTP {status}): check the key, its owner's e-mail, "
                "and that BI is enabled globally and for the workspace"
            )
        if status == 404:
            raise BaleiaError(
                f"{path} is not served (HTTP 404): "
                "this Baleia does not serve the semantic catalog yet"
            )
        if status != 200:
            raise BaleiaError(f"{path} returned HTTP {status}")
        try:
            body = response.json()
        except ValueError:
            raise BaleiaError(f"{path} did not return JSON") from None
        if not isinstance(body, dict):
            raise BaleiaError(f"{path} did not return an object")
        version = body.get("contract_version")
        if version != SUPPORTED_CONTRACT_VERSION:
            raise BaleiaContractError(
                f"Baleia's semantic catalog contract version is {version!r}; "
                f"this connector supports {SUPPORTED_CONTRACT_VERSION}"
            )
        return body

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        delay = min(0.5 * 2 ** (attempt - 1), MAX_RETRY_DELAY_SECONDS)
        if retry_after:
            requested = _retry_after_seconds(retry_after, self._now())
            if requested is not None:
                delay = min(max(requested, 0.0), MAX_RETRY_DELAY_SECONDS)
        logger.debug("retrying Baleia request in %.1fs (attempt %d)", delay, attempt)
        self._sleep(delay)


def _retry_after_seconds(value: str, now: datetime) -> float | None:
    """Reads Retry-After as seconds or as an HTTP-date; None when invalid."""
    with contextlib.suppress(ValueError):
        return float(value)
    with contextlib.suppress(TypeError, ValueError, IndexError):
        when = parsedate_to_datetime(value)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return (when - now).total_seconds()
    return None
