import baleia_openmetadata


def test_version_is_exposed() -> None:
    assert isinstance(baleia_openmetadata.__version__, str)
