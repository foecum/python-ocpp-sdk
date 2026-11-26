import ocpp_sdk


def test_version_is_a_string() -> None:
    assert isinstance(ocpp_sdk.__version__, str)
