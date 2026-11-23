"""Connection settings of the Baleia connector.

OpenMetadata passes a custom connector's settings as ``connectionOptions``, a
map of strings. :class:`BaleiaConfig` validates them once, so the rest of the
connector works with typed values.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# The environment variable read when ``biKey`` is not in the options, so the
# key can stay out of OpenMetadata's stored service configuration.
BI_KEY_ENV = "BALEIA_BI_KEY"

DEFAULT_TIMEOUT_SECONDS = 30.0


class ConfigError(ValueError):
    """The connection options are missing or invalid."""


def _truthy(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ConfigError(f"expected true or false, got {value!r}")


@dataclass(frozen=True)
class BaleiaConfig:
    """Validated connection settings.

    ``url`` is the origin of Baleia's BI gateway, the same host and port the
    Trino connector uses. ``bi_key`` is never part of ``repr``.
    """

    url: str
    email: str
    bi_key: str = field(repr=False)
    trino_services: tuple[str, ...]
    verify_tls: bool = True
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_options(
        cls, options: Mapping[str, str] | None, env: Mapping[str, str] | None = None
    ) -> BaleiaConfig:
        """Builds the settings from OpenMetadata's ``connectionOptions``.

        Options:

        - ``baleiaUrl`` (required): the BI gateway origin, ``https://host:port``.
        - ``biKeyEmail`` (required): the BI key owner's e-mail.
        - ``biKey``: the BI key; when absent, read from ``BALEIA_BI_KEY``.
        - ``trinoServiceNames`` (required): comma-separated OpenMetadata
          database services that ingest the same workspace through the gateway.
        - ``allowHttp``: ``true`` to accept a plain ``http`` URL (internal
          networks only; the BI key is a password).
        - ``verifyTls``: ``false`` to skip certificate verification (tests only).
        - ``timeoutSeconds``: request timeout, default 30.
        """
        options = dict(options or {})
        env = os.environ if env is None else env

        url = (options.get("baleiaUrl") or "").strip().rstrip("/")
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ConfigError(
                "baleiaUrl must be the BI gateway origin, e.g. https://bi.example.com"
            )
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ConfigError("baleiaUrl must not contain credentials, a query or a fragment")
        if parts.path not in {"", "/"}:
            raise ConfigError("baleiaUrl must be an origin without a path")
        if parts.scheme == "http" and not _truthy(options.get("allowHttp"), default=False):
            raise ConfigError(
                "baleiaUrl must use https; set allowHttp to true on an internal network"
            )

        email = (options.get("biKeyEmail") or "").strip()
        if not email:
            raise ConfigError("biKeyEmail is required")

        bi_key = (options.get("biKey") or env.get(BI_KEY_ENV) or "").strip()
        if not bi_key:
            raise ConfigError(f"biKey is required, in the options or in {BI_KEY_ENV}")

        services = tuple(
            name.strip()
            for name in (options.get("trinoServiceNames") or "").split(",")
            if name.strip()
        )
        if not services:
            raise ConfigError("trinoServiceNames must name at least one OpenMetadata Trino service")

        raw_timeout = (options.get("timeoutSeconds") or "").strip()
        try:
            timeout = float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT_SECONDS
        except ValueError as err:
            raise ConfigError("timeoutSeconds must be a number") from err
        if not 0 < timeout <= 300:
            raise ConfigError("timeoutSeconds must be between 0 and 300")

        return cls(
            url=url,
            email=email,
            bi_key=bi_key,
            trino_services=services,
            verify_tls=_truthy(options.get("verifyTls"), default=True),
            timeout_seconds=timeout,
        )
