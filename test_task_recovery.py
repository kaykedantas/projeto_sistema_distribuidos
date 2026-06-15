"""
test_task_recovery.py — Testa a tolerância a falhas de tarefa no master.py (raiz).

Cobre a correção da Sprint 3.2 (entrega at-least-once):
  T1. Worker cai com tarefa em andamento  -> tarefa volta para a fila (Cenário 1).
  T2. Worker reporta NOK                   -> tarefa é reenfileirada (retentativa).
  T3. NOK acima do limite                  -> tarefa é descartada (dead-letter).
  T4. Worker reporta OK                     -> tarefa NÃO volta; in_flight limpo.

Rode com:  python test_task_recovery.py   (sem instalar nada)
"""

import asyncio
import contextlib
from collections import deque

import master as M  # master.py da raiz (arquivo unificado)


async def _sobe_master(tasks, max_attempts=3):
    m = M.Master("127.0.0.1", 0, master_id="MA", name="MA",
                 tasks=tasks, max_task_attempts=max_attempts)
    server = await asyncio.start_server(m.handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return m, server, port


async def _fecha(server):
    server.close()
    with contextlib.suppress(Exception):
        await server.wait_closed()


async def _present_e_pega_query(reader, writer, uuid_):
    await M.send_message(writer, {"WORKER": "ALIVE", "WORKER_UUID": uuid_})
    return await asyncio.wait_for(M.read_message(reader), timeout=2)


# ── T1: queda no meio da tarefa reenfileira ──────────────────────────

async def test_disconnect_reenfileira():
    m, server, port = await _sobe_master(["T1"])
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        resp = await _present_e_pega_query(reader, writer, "W1")
        assert resp == {"TASK": "QUERY", "USER": "T1"}, resp
        assert list(m.tasks) == [], "tarefa deveria ter saído da fila"
        assert m.in_flight.get("W1") == "T1", "tarefa deveria estar em andamento"

        # Worker CAI antes de reportar STATUS (simula queda de conexão/PC).
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()

        # Dá tempo do finally do handle_client rodar no master.
        for _ in range(50):
            await asyncio.sleep(0.02)
            if list(m.tasks) == ["T1"]:
                break

        assert list(m.tasks) == ["T1"], f"esperado reenfileiramento; fila={list(m.tasks)}"
        assert "W1" not in m.in_flight, "in_flight deveria ter sido limpo"
    finally:
        await _fecha(server)


# ── T2: NOK reenfileira (retentativa) ────────────────────────────────

async def test_nok_reenfileira():
    m, server, port = await _sobe_master(["T1"], max_attempts=3)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        resp = await _present_e_pega_query(reader, writer, "W1")
        assert resp["USER"] == "T1"

        await M.send_message(writer, {"STATUS": "NOK", "TASK": "QUERY", "WORKER_UUID": "W1"})
        ack = await asyncio.wait_for(M.read_message(reader), timeout=2)
        assert ack == {"STATUS": "ACK", "WORKER_UUID": "W1"}, ack

        assert list(m.tasks) == ["T1"], "NOK deveria reenfileirar a tarefa"
        assert m.task_attempts.get("T1") == 1, "deveria contar 1 tentativa"
        assert "W1" not in m.in_flight
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
    finally:
        await _fecha(server)


# ── T3: NOK acima do limite vira dead-letter ─────────────────────────

async def test_nok_deadletter_no_limite():
    # max_attempts=2 -> 1ª NOK reenfileira, 2ª NOK descarta.
    m, server, port = await _sobe_master(["T1"], max_attempts=2)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        # Tentativa 1 -> NOK -> reenfileira (attempts=1 < 2)
        resp = await _present_e_pega_query(reader, writer, "W1")
        assert resp["USER"] == "T1"
        await M.send_message(writer, {"STATUS": "NOK", "TASK": "QUERY", "WORKER_UUID": "W1"})
        await asyncio.wait_for(M.read_message(reader), timeout=2)
        assert list(m.tasks) == ["T1"]

        # Tentativa 2 -> NOK -> dead-letter (attempts=2, 2 < 2 é falso)
        resp = await _present_e_pega_query(reader, writer, "W1")
        assert resp["USER"] == "T1"
        await M.send_message(writer, {"STATUS": "NOK", "TASK": "QUERY", "WORKER_UUID": "W1"})
        await asyncio.wait_for(M.read_message(reader), timeout=2)

        assert list(m.tasks) == [], f"tarefa deveria ter sido descartada; fila={list(m.tasks)}"
        assert "T1" not in m.task_attempts, "contador deveria ter sido limpo no descarte"
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
    finally:
        await _fecha(server)


# ── T4: OK conclui e não reenfileira ─────────────────────────────────

async def test_ok_conclui():
    m, server, port = await _sobe_master(["T1"])
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        resp = await _present_e_pega_query(reader, writer, "W1")
        assert resp["USER"] == "T1"

        await M.send_message(writer, {"STATUS": "OK", "TASK": "QUERY", "WORKER_UUID": "W1"})
        ack = await asyncio.wait_for(M.read_message(reader), timeout=2)
        assert ack == {"STATUS": "ACK", "WORKER_UUID": "W1"}, ack

        # Fecha a conexão DEPOIS do OK: não pode reenfileirar.
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        await asyncio.sleep(0.2)

        assert list(m.tasks) == [], f"OK não deveria reenfileirar; fila={list(m.tasks)}"
        assert "W1" not in m.in_flight
        assert "T1" not in m.task_attempts
    finally:
        await _fecha(server)


TESTS = [
    test_disconnect_reenfileira,
    test_nok_reenfileira,
    test_nok_deadletter_no_limite,
    test_ok_conclui,
]


def main():
    import logging
    logging.disable(logging.CRITICAL)  # silencia logs do master durante os testes
    passed = 0
    for t in TESTS:
        try:
            asyncio.run(t())
            print(f"PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL  {t.__name__}: {e!r}")
    print("=" * 50)
    print(f"Resultado: {passed}/{len(TESTS)} testes passaram")
    raise SystemExit(0 if passed == len(TESTS) else 1)


if __name__ == "__main__":
    main()
