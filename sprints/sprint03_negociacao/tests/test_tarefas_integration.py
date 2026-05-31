"""Testes de integração da Sprint 2 sobre sockets TCP reais.

Cobre os casos de sala CT01–CT05 e o ciclo completo (present→QUERY→OK→ACK).
Usa ``asyncio.run`` internamente (não depende de pytest-asyncio).
"""

import asyncio
import contextlib

from src.heartbeat import master_async, messaging, worker_async


async def _abre(port, tasks):
    """Sobe um Master em ``port`` com a fila ``tasks`` e retorna (master, task)."""
    m = master_async.Master("127.0.0.1", port, master_id="Master_A", tasks=tasks)
    server = asyncio.create_task(m.start())
    await asyncio.sleep(0.15)  # deixa o servidor bindar
    return m, server


async def _fecha(server):
    server.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await server


async def _envia(port, payload):
    """Abre conexão, envia um payload e devolve a resposta (uma mensagem)."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    await messaging.send_message(writer, payload)
    resp = await asyncio.wait_for(messaging.read_message(reader), timeout=2)
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
    return resp


def test_ct01_worker_local_recebe_query():
    async def cenario():
        m, server = await _abre(9201, ["Michel"])
        resp = await _envia(9201, {"WORKER": "ALIVE", "WORKER_UUID": "W-123"})
        await _fecha(server)
        return resp
    resp = asyncio.run(cenario())
    assert resp["TASK"] == "QUERY" and resp["USER"] == "Michel"


def test_ct02_worker_emprestado_recebe_query_e_e_registrado():
    async def cenario():
        m, server = await _abre(9202, ["Julia"])
        resp = await _envia(9202, {"WORKER": "ALIVE", "WORKER_UUID": "W-999",
                                   "SERVER_UUID": "Master-B"})
        emprestado = m.workers.get("W-999", {}).get("emprestado")
        await _fecha(server)
        return resp, emprestado
    resp, emprestado = asyncio.run(cenario())
    assert resp["TASK"] == "QUERY" and resp["USER"] == "Julia"
    assert emprestado is True


def test_ct03_fila_vazia_recebe_no_task():
    async def cenario():
        m, server = await _abre(9203, [])
        resp = await _envia(9203, {"WORKER": "ALIVE", "WORKER_UUID": "W-123"})
        await _fecha(server)
        return resp
    resp = asyncio.run(cenario())
    assert resp == {"TASK": "NO_TASK"}


def test_ct04_status_ok_recebe_ack():
    async def cenario():
        m, server = await _abre(9204, [])
        resp = await _envia(9204, {"STATUS": "OK", "TASK": "QUERY",
                                   "WORKER_UUID": "W-123"})
        await _fecha(server)
        return resp
    resp = asyncio.run(cenario())
    assert resp["STATUS"] == "ACK"


def test_ct05_status_nok_recebe_ack():
    async def cenario():
        m, server = await _abre(9205, [])
        resp = await _envia(9205, {"STATUS": "NOK", "TASK": "QUERY",
                                   "WORKER_UUID": "W-123"})
        await _fecha(server)
        return resp
    resp = asyncio.run(cenario())
    assert resp["STATUS"] == "ACK"


def test_ciclo_completo_present_query_ok_ack():
    """Ciclo completo usando o Worker real, com process_task forçado a OK."""
    original = worker_async.process_task

    async def _ok(*a, **k):
        return "OK"

    async def cenario():
        m, server = await _abre(9210, ["Michel"])
        worker_async.process_task = _ok  # determinístico
        try:
            resultado = await worker_async.do_one_task("127.0.0.1", 9210, "W-123")
            concluidas = m.workers.get("W-123", {}).get("concluidas")
        finally:
            worker_async.process_task = original
            await _fecha(server)
        return resultado, concluidas

    resultado, concluidas = asyncio.run(cenario())
    assert resultado == "OK"
    assert concluidas == 1
