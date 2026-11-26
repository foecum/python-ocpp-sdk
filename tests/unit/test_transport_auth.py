import ssl

import pytest

from ocpp_sdk.transport import auth


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ("CP1", True),
        ("a" * 48, True),
        ("a" * 49, False),
        ("", False),
        ("a:b", False),
        ("a/b", False),
    ],
)
def test_valid_charge_point_id(value: str, ok: bool) -> None:
    assert auth.valid_charge_point_id(value) is ok


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/CP1", "CP1"),
        ("/ocpp/CP1", "CP1"),
        ("/ocpp/CP1?a=b", "CP1"),
        ("/ocpp/CP%2D1", "CP-1"),
        ("/ocpp/", None),
        ("/", None),
        ("", None),
        ("/ocpp/a%3Ab", None),
        ("/ocpp/a%2Fb", None),
        (f"/ocpp/{'x' * 49}", None),
    ],
)
def test_charge_point_id_from_path(path: str, expected: str | None) -> None:
    assert auth.charge_point_id_from_path(path) == expected


def test_basic_auth_round_trip_and_rejects() -> None:
    assert auth.parse_basic_auth(auth.basic_auth_header("CP-1", "p:w")) == ("CP-1", "p:w")
    assert auth.parse_basic_auth("basic " + auth.basic_auth_header("a", "b")[6:]) == ("a", "b")
    assert auth.parse_basic_auth(None) is None
    assert auth.parse_basic_auth("") is None
    assert auth.parse_basic_auth("Bearer abc") is None
    assert auth.parse_basic_auth("Basic !!!notbase64") is None
    assert auth.parse_basic_auth("Basic /w==") is None  # not UTF-8
    assert auth.parse_basic_auth("Basic bm9jb2xvbg==") is None  # no colon


def cert(cn: list[str], org: list[str]) -> dict[str, object]:
    subject = tuple([(("organizationName", o),) for o in org] + [(("commonName", c),) for c in cn])
    return {"subject": subject}


def test_certificate_identity() -> None:
    ok = auth.certificate_identity_ok
    assert ok(cert(["CP1"], []), "CP1")
    assert not ok(cert(["CP2"], []), "CP1")
    assert not ok(cert([], []), "CP1")
    assert not ok(cert(["CP1", "CP1"], []), "CP1")
    assert not ok(None, "CP1")
    assert not ok({}, "CP1")
    assert ok(cert(["CP1"], ["Acme Charging Ltd"]), "CP1", "Acme")
    assert not ok(cert(["CP1"], ["Other"]), "CP1", "Acme")
    assert not ok(cert(["CP1"], []), "CP1", "Acme")


def test_client_context_is_tls12_plus() -> None:
    ctx = auth.client_ssl_context()
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    names = {c["name"] for c in ctx.get_ciphers() if c["protocol"] == "TLSv1.2"}
    assert names
    assert all("GCM" in n for n in names)
