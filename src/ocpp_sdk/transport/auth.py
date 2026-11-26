"""Basic auth, TLS contexts and client-certificate identity checks.

Example:
    >>> from ocpp_sdk.transport.auth import basic_auth_header, parse_basic_auth
    >>> header = basic_auth_header("CP001", "secret")
    >>> parse_basic_auth(header)
    ('CP001', 'secret')
"""

from __future__ import annotations

import base64
import binascii
import ssl
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote, urlsplit

__all__ = [
    "MAX_ID_LENGTH",
    "basic_auth_header",
    "certificate_identity_ok",
    "charge_point_id_from_path",
    "client_ssl_context",
    "parse_basic_auth",
    "server_ssl_context",
    "valid_charge_point_id",
]

MAX_ID_LENGTH = 48

# TLS 1.2 suites of the OCPP security profiles (ECDHE + AES-GCM); TLS 1.3 suites are fixed.
_CIPHERS = (
    "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:"
    "ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384"
)


def valid_charge_point_id(value: str) -> bool:
    """A charge point ID is 1..48 characters without ``:`` or ``/``.

    Example:
        >>> valid_charge_point_id("CP-001"), valid_charge_point_id("a:b")
        (True, False)
    """
    return 0 < len(value) <= MAX_ID_LENGTH and ":" not in value and "/" not in value


def charge_point_id_from_path(path: str) -> str | None:
    """Return the charge point ID (last URL path segment, percent-decoded) or ``None``.

    Example:
        >>> charge_point_id_from_path("/ocpp/CP%2D001?x=1")
        'CP-001'
        >>> charge_point_id_from_path("/ocpp/") is None
        True
    """
    segment = unquote(urlsplit(path).path.rsplit("/", 1)[-1])
    return segment if valid_charge_point_id(segment) else None


def basic_auth_header(username: str, password: str) -> str:
    """Build the ``Authorization`` header value for HTTP Basic auth."""
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def parse_basic_auth(header: str | None) -> tuple[str, str] | None:
    """Parse an ``Authorization`` header; ``None`` if it is absent or not valid Basic auth."""
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "basic":
        return None
    try:
        decoded = base64.b64decode(token.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    username, sep, password = decoded.partition(":")
    return (username, password) if sep else None


def certificate_identity_ok(
    certificate: Mapping[str, Any] | None,
    charge_point_id: str,
    operator_name: str | None = None,
) -> bool:
    """Security profile 3: subject CN must equal the ID; O must contain the operator name.

    ``certificate`` is the dict returned by ``ssl.SSLSocket.getpeercert()``
    (A00.FR.404/405/511).
    """
    if not certificate:
        return False
    common_names: list[str] = []
    organizations: list[str] = []
    for rdn in certificate.get("subject", ()):
        for key, value in rdn:
            if key == "commonName":
                common_names.append(value)
            elif key == "organizationName":
                organizations.append(value)
    if common_names != [charge_point_id]:
        return False
    return operator_name is None or any(operator_name in o for o in organizations)


def server_ssl_context(
    certfile: str,
    keyfile: str | None = None,
    *,
    password: str | None = None,
    client_ca: str | None = None,
) -> ssl.SSLContext:
    """TLS context for a CSMS: TLS 1.2+, GCM suites.

    Passing ``client_ca`` makes a client certificate mandatory (security profile 3).
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.set_ciphers(_CIPHERS)
    context.load_cert_chain(certfile, keyfile, password)
    if client_ca is not None:
        context.load_verify_locations(client_ca)
        context.verify_mode = ssl.CERT_REQUIRED
    return context


def client_ssl_context(
    *,
    cafile: str | None = None,
    certfile: str | None = None,
    keyfile: str | None = None,
    password: str | None = None,
) -> ssl.SSLContext:
    """TLS context for a charge point: TLS 1.2+, GCM suites, server verified.

    Pass ``certfile`` (and ``keyfile``) for a client certificate (security profile 3).
    """
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=cafile)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.set_ciphers(_CIPHERS)
    if certfile is not None:
        context.load_cert_chain(certfile, keyfile, password)
    return context
