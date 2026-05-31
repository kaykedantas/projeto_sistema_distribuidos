"""Testes de integração da negociação M2M (CT01, CT02, CT03, CT07)."""

import asyncio
import contextlib

from src.heartbeat import master_async


async def _sobe_master(name, ociosos=0, carga_alta=False):
    m = master_async.Master("127.0.0.1", 0, master_id=name, name=name)
    m.idle_workers = [{"id": f"{name}{i}", "address": f"ip:{i}"} for i in range(ociosos)]
    if carga_alta:
        m.current_load = 999
        m._saturated = True
    server = await asyncio.start_server(m.handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return m, server, port


async def _fecha(server):
    server.close()
    with contextlib.suppress(Exception):
        await server.wait_closed()


def test_ct01_help_aceito():
    async def cenario():
        b, sb, pb = await _sobe_master("B", ociosos=2)
        a, sa, pa = await _sobe_master("A")
        a.neighbors["B"] = ("127.0.0.1", pb)
        resp = await a.request_help_to("B", workers_needed=2, timeout=2.0)
        await _fecha(sb); await _fecha(sa)
        return resp

    resp = asyncio.run(cenario())
    assert resp["type"] == "response_accepted"
    assert resp["payload"]["workers_offered"] == 2


def test_ct02_help_recusado():
    async def cenario():
        b, sb, pb = await _sobe_master("B", ociosos=0, carga_alta=True)
        a, sa, pa = await _sobe_master("A")
        a.neighbors["B"] = ("127.0.0.1", pb)
        resp = await a.request_help_to("B", workers_needed=2, timeout=2.0)
        await _fecha(sb); await _fecha(sa)
        return resp

    resp = asyncio.run(cenario())
    assert resp["type"] == "response_rejected"
    assert resp["payload"]["reason"] in ("high_load", "no_workers_available")


def test_ct03_correlacao_request_id_concorrente():
    async def cenario():
        b, sb, pb = await _sobe_master("B", ociosos=2)
        c, sc, pc = await _sobe_master("C", ociosos=2)
        a, sa, pa = await _sobe_master("A")
        a.neighbors["B"] = ("127.0.0.1", pb)
        a.neighbors["C"] = ("127.0.0.1", pc)
        # dois pedidos concorrentes
        rb, rc = await asyncio.gather(
            a.request_help_to("B", workers_needed=1, timeout=2.0),
            a.request_help_to("C", workers_needed=1, timeout=2.0),
        )
        await _fecha(sb); await _fecha(sc); await _fecha(sa)
        return rb, rc

    rb, rc = asyncio.run(cenario())
    assert rb["type"] == "response_accepted"
    assert rc["type"] == "response_accepted"


def test_ct07_timeout_sem_resposta():
    async def cenario():
        a, sa, pa = await _sobe_master("A")
        a.neighbors["B"] = ("127.0.0.1", 59998)  # ninguém escutando
        resp = await a.request_help_to("B", workers_needed=1, timeout=0.5)
        await _fecha(sa)
        return resp

    assert asyncio.run(cenario()) is None
