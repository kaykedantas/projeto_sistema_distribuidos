"""Testes do bootstrap do Worker: handshake de eleição e fallback."""

import asyncio
import contextlib

from src.heartbeat import worker_async, master_async, discovery


def test_connect_and_confirm_ok():
    async def cenario():
        m = master_async.Master("127.0.0.1", 0, master_id="MASTER_1", name="MASTER_1")
        server = await asyncio.start_server(m.handle_client, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        master = {"MASTER_NAME": "MASTER_1", "MASTER_IP": "127.0.0.1", "MASTER_PORT": port}
        alvo = await worker_async.connect_and_confirm(master, "W-1")
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
        return alvo

    alvo = asyncio.run(cenario())
    assert alvo is not None and alvo[0] == "127.0.0.1"


def test_bootstrap_sem_master_aplica_fallback():
    """discover devolve [] -> NO_MASTER_FOUND; desiste após max_attempts sem travar."""
    original = discovery.discover

    async def fake_discover(*a, **k):
        return []

    async def cenario():
        discovery.discover = fake_discover
        try:
            return await worker_async.bootstrap("W-1", max_attempts=2,
                                                base_backoff=0.01)
        finally:
            discovery.discover = original

    assert asyncio.run(cenario()) is None
