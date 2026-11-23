import pytest

from baleia_openmetadata.config import BI_KEY_ENV, BaleiaConfig, ConfigError

VALID = {
    "baleiaUrl": "https://bi.example.com:8443/",
    "biKeyEmail": "owner@example.com",
    "biKey": "bal_secret",
    "trinoServiceNames": " trino-sales , trino-ops ,",
}


def test_valid_options() -> None:
    cfg = BaleiaConfig.from_options(VALID, env={})
    assert cfg.url == "https://bi.example.com:8443"
    assert cfg.email == "owner@example.com"
    assert cfg.trino_services == ("trino-sales", "trino-ops")
    assert cfg.verify_tls is True
    assert cfg.timeout_seconds == 30.0
    assert "bal_secret" not in repr(cfg)


def test_key_from_environment() -> None:
    options = {k: v for k, v in VALID.items() if k != "biKey"}
    assert BaleiaConfig.from_options(options, env={BI_KEY_ENV: "bal_env"}).bi_key == "bal_env"
    with pytest.raises(ConfigError, match="biKey"):
        BaleiaConfig.from_options(options, env={})


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"baleiaUrl": "bi.example.com"}, "origin"),
        ({"baleiaUrl": "https://bi.example.com/baleia"}, "without a path"),
        ({"baleiaUrl": "https://user:pw@bi.example.com"}, "credentials"),
        ({"baleiaUrl": "http://bi.internal:8443"}, "https"),
        ({"biKeyEmail": " "}, "biKeyEmail"),
        ({"trinoServiceNames": " , "}, "trinoServiceNames"),
        ({"timeoutSeconds": "abc"}, "number"),
        ({"timeoutSeconds": "0"}, "between"),
        ({"verifyTls": "maybe"}, "true or false"),
    ],
)
def test_invalid_options(override: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        BaleiaConfig.from_options({**VALID, **override}, env={})


def test_http_needs_explicit_opt_in() -> None:
    cfg = BaleiaConfig.from_options(
        {**VALID, "baleiaUrl": "http://bi.internal:8443", "allowHttp": "true"}, env={}
    )
    assert cfg.url == "http://bi.internal:8443"
