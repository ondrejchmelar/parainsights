"""The suite runs with no network, and this makes that a rule rather than a habit.

Any socket a test opens to somewhere other than this machine is refused with an error
naming the address, so a test that would have downloaded real tiles, a forecast or a
CDN script fails where it stands instead of passing slowly while online and failing
offline. Local servers (the synthetic tile servers, the flymet stand-in) are untouched.
Headless Chrome is a separate process and is fenced separately, by the resolver rule in
`tests/test_view3d_gl.CHROME_FLAGS`.
"""

import ipaddress
import socket

import pytest

_connect = socket.socket.connect


def _local(address) -> bool:
    if not isinstance(address, tuple):          # a Unix socket
        return True
    host = address[0]
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _guarded(self, address):
    if not _local(address):
        raise RuntimeError(f"a test tried to reach the network: {address!r}")
    return _connect(self, address)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _guarded)
