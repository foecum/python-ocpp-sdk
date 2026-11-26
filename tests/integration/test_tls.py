import ssl
from pathlib import Path
from typing import Any

import pytest
import trustme
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus
from websockets.typing import Subprotocol

from ocpp_sdk.transport import Client, Reconnect, Server
from ocpp_sdk.transport.auth import basic_auth_header, client_ssl_context, server_ssl_context
from tests.integration.helpers import Sinks, until

P16 = [Subprotocol("ocpp1.6")]


class Pki:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.ca = trustme.CA()
        self.ca_file = self._write("ca.pem", self.ca.cert_pem)
        server = self.ca.issue_cert("localhost", "127.0.0.1")
        self.server_cert = self._write("server.pem", server.cert_chain_pems[0])
        self.server_key = self._write("server.key", server.private_key_pem)

    def _write(self, name: str, blob: Any) -> str:
        path = self.tmp / name
        blob.write_to_path(path)
        return str(path)

    def client_cert(self, cn: str, org: str | None = None) -> tuple[str, str]:
        cert = self.ca.issue_cert(cn, common_name=cn, organization_name=org)
        return (
            self._write(f"{cn}.pem", cert.cert_chain_pems[0]),
            self._write(f"{cn}.key", cert.private_key_pem),
        )

    def server_context(self, mutual: bool = False) -> ssl.SSLContext:
        return server_ssl_context(
            self.server_cert, self.server_key, client_ca=self.ca_file if mutual else None
        )

    def client_context(self, cert: tuple[str, str] | None = None) -> ssl.SSLContext:
        return client_ssl_context(
            cafile=self.ca_file,
            certfile=cert[0] if cert else None,
            keyfile=cert[1] if cert else None,
        )


@pytest.fixture
def pki(tmp_path: Path) -> Pki:
    return Pki(tmp_path)


def wss(server: Server, cp: str = "CP1") -> str:
    return f"wss://localhost:{server.port}/ocpp/{cp}"


def test_server_context_requires_tls12_and_optionally_client_certs(pki: Pki) -> None:
    plain = pki.server_context()
    assert plain.minimum_version == ssl.TLSVersion.TLSv1_2
    assert plain.verify_mode == ssl.CERT_NONE
    assert pki.server_context(mutual=True).verify_mode == ssl.CERT_REQUIRED


async def test_profile_2_tls_with_basic_auth(pki: Pki) -> None:
    sinks, client_sinks = Sinks(), Sinks()
    server = Server(
        sinks.on_connect,
        port=0,
        ssl_context=pki.server_context(),
        authenticate=lambda cp, pw: pw == "pw",
    )
    async with server:
        async with Client(
            wss(server), client_sinks.on_connect, password="pw", ssl_context=pki.client_context()
        ) as client:
            assert client.connection is not None
            assert server.connection("CP1") is not None
        bad = Client(
            wss(server),
            client_sinks.on_connect,
            password="x",
            ssl_context=pki.client_context(),
            reconnect=None,
        )
        bad.start()
        await until(lambda: bad._finished.is_set())
        await bad.close()


async def test_client_rejects_an_untrusted_server_certificate(pki: Pki) -> None:
    sinks = Sinks()
    async with Server(sinks.on_connect, port=0, ssl_context=pki.server_context()) as server:
        other_ca = trustme.CA()
        ca_file = tmp = pki.tmp / "other-ca.pem"
        other_ca.cert_pem.write_to_path(tmp)
        client = Client(
            wss(server),
            sinks.on_connect,
            ssl_context=client_ssl_context(cafile=str(ca_file)),
            reconnect=None,
        )
        client.start()
        await until(lambda: client._finished.is_set())
        await client.close()
        assert sinks.sinks == []


async def test_plain_client_cannot_use_a_tls_server(pki: Pki) -> None:
    sinks = Sinks()
    async with Server(sinks.on_connect, port=0, ssl_context=pki.server_context()) as server:
        client = Client(
            f"ws://127.0.0.1:{server.port}/CP1", sinks.on_connect, reconnect=None, open_timeout=1
        )
        client.start()
        await until(lambda: client._finished.is_set())
        await client.close()
        assert sinks.sinks == []


async def test_profile_3_certificate_identity(pki: Pki) -> None:
    sinks = Sinks()
    server = Server(
        sinks.on_connect,
        port=0,
        ssl_context=pki.server_context(mutual=True),
        check_certificate_identity=True,
    )
    async with server:
        good = pki.client_cert("CP1")
        async with connect(
            wss(server, "CP1"), subprotocols=P16, ssl=pki.client_context(good)
        ) as ws:
            assert ws.subprotocol == "ocpp1.6"
            await until(lambda: server.connection("CP1") is not None)
            conn = server.connection("CP1")
            assert conn is not None
            assert conn.peer_certificate is not None
        # CN of the certificate is CP1 but the URL says CP2 -> 403
        with pytest.raises(InvalidStatus) as info:
            async with connect(wss(server, "CP2"), subprotocols=P16, ssl=pki.client_context(good)):
                pass
        assert info.value.response.status_code == 403


async def test_profile_3_requires_a_client_certificate(pki: Pki) -> None:
    sinks = Sinks()
    server = Server(
        sinks.on_connect,
        port=0,
        ssl_context=pki.server_context(mutual=True),
        check_certificate_identity=True,
    )
    async with server:
        client = Client(
            wss(server), sinks.on_connect, ssl_context=pki.client_context(), reconnect=None
        )
        client.start()
        await until(lambda: client._finished.is_set())
        await client.close()
        assert sinks.sinks == []


async def test_profile_3_certificate_from_an_unknown_ca_is_refused(pki: Pki) -> None:
    sinks = Sinks()
    server = Server(
        sinks.on_connect,
        port=0,
        ssl_context=pki.server_context(mutual=True),
        check_certificate_identity=True,
    )
    async with server:
        rogue = trustme.CA()
        cert = rogue.issue_cert("CP1", common_name="CP1")
        cert_file, key_file = pki.tmp / "rogue.pem", pki.tmp / "rogue.key"
        cert.cert_chain_pems[0].write_to_path(cert_file)
        cert.private_key_pem.write_to_path(key_file)
        client = Client(
            wss(server),
            sinks.on_connect,
            ssl_context=pki.client_context((str(cert_file), str(key_file))),
            reconnect=None,
        )
        client.start()
        await until(lambda: client._finished.is_set())
        await client.close()
        assert sinks.sinks == []


@pytest.mark.parametrize(
    ("org", "operator", "status"),
    [("Acme Charging", "Acme", None), ("Other Org", "Acme", 403), (None, "Acme", 403)],
)
async def test_profile_3_operator_name(
    pki: Pki, org: str | None, operator: str, status: int | None
) -> None:
    sinks = Sinks()
    server = Server(
        sinks.on_connect,
        port=0,
        ssl_context=pki.server_context(mutual=True),
        check_certificate_identity=True,
        operator_name=operator,
    )
    cert = pki.client_cert("CP1", org)
    async with server:
        if status is None:
            async with connect(wss(server), subprotocols=P16, ssl=pki.client_context(cert)) as ws:
                assert ws.subprotocol == "ocpp1.6"
        else:
            with pytest.raises(InvalidStatus) as info:
                async with connect(wss(server), subprotocols=P16, ssl=pki.client_context(cert)):
                    pass
            assert info.value.response.status_code == status


async def test_identity_check_without_tls_is_forbidden() -> None:
    sinks = Sinks()
    server = Server(sinks.on_connect, port=0, check_certificate_identity=True)
    async with server:
        with pytest.raises(InvalidStatus) as info:
            async with connect(f"ws://127.0.0.1:{server.port}/CP1", subprotocols=P16):
                pass
        assert info.value.response.status_code == 403


def test_basic_auth_header_is_not_used_when_unused() -> None:
    assert basic_auth_header("a", "b").startswith("Basic ")


async def test_reconnect_type_is_exported() -> None:
    assert Reconnect().repeat_times == 6
