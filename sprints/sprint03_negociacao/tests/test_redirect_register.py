"""Testes de redirecionamento e registro de Worker emprestado (CT04, CT05)."""

import asyncio
import contextlib

from src.heartbeat import master_async, worker_async, messaging


async def _sobe(name, tasks=None):
    m = master_async.Master("127.0.0.1", 0, master_id=name, name=name, tasks=tasks)
    server = await asyncio.start_server(m.handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return m, server, port


async def _fecha(server):
    server.close()
    with contextlib.suppress(Exception):
        await server.wait_closed()


def test_ct04_registro_worker_emprestado():
    async def cenario():
        a, sa, pa = await _sobe("MASTER_A")
        ok = await worker_async.register_as_temporary(
            "127.0.0.1", pa, "B1", "127.0.0.1:9000")
        await asyncio.sleep(0.1)  # deixa o Master processar
        registrado = "B1" in a.borrowed_in
        await _fecha(sa)
        return ok, registrado

    ok, registrado = asyncio.run(cenario())
    assert ok is True
    assert registrado is True


def test_ct05_tarefa_em_worker_emprestado():
    """O emprestado opera pelo ciclo da Sprint 02 com SERVER_UUID = Master origem."""
    async def cenario():
        a, sa, pa = await _sobe("MASTER_A", tasks=["Michel"])
        # registra como emprestado
        await worker_async.register_as_temporary("127.0.0.1", pa, "B1", "127.0.0.1:9000")
        await asyncio.sleep(0.05)
        # agora o worker emprestado pede trabalho com SERVER_UUID = origem
        resultado = await worker_async.do_one_task("127.0.0.1", pa, "B1",
                                                   origin_master="MASTER_B")
        emprestado = a.workers.get("B1", {}).get("emprestado")
        await _fecha(sa)
        return resultado, emprestado

    resultado, emprestado = asyncio.run(cenario())
    assert resultado in ("OK", "NOK")
    assert emprestado is True
