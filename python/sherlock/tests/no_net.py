"""Run a script with outbound connections to non-loopback hosts or a given port forbidden.

Usage: python no_net.py <forbidden_port> <script.py> [args...]
A forbidden attempt writes $NO_NET_MARKER and raises, so tests can prove zero network calls.
"""

import os
import runpy
import socket
import sys

forbidden = int(sys.argv[1])
real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex


def _check(addr):
    if isinstance(addr, tuple) and (addr[1] == forbidden or addr[0] not in ("127.0.0.1", "::1", "localhost")):
        with open(os.environ["NO_NET_MARKER"], "a") as f:
            f.write(f"{addr}\n")
        raise ConnectionError(f"network attempted: {addr}")


def connect(self, addr):
    _check(addr)
    return real_connect(self, addr)


def connect_ex(self, addr):
    _check(addr)
    return real_connect_ex(self, addr)


socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
sys.argv = sys.argv[2:]
runpy.run_path(sys.argv[0], run_name="__main__")
