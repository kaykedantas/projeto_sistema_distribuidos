"""Testes de integração Worker <-> Master sobre sockets TCP reais.

Cada teste sobe um Master em uma porta de loopback, exercita o fluxo e
encerra o servidor. Usa ``asyncio.run`` internamente, de modo que NÃO depende
do plugin pytest-asyncio (roda com pytest puro ou pelo runner standalone).
"""

import asyncio
import contextlib

from src.heartbeat import master_async, worker_async


async def _com_master(port: int, coro, master_id: str = "Master_A"):
    """Sobe o Master em ``port``, espera bindar, executa ``coro(port)`` e
    garante o encerramento do servidor ao final."""
    server_task = asyncio.create_task(
        master_async.run_server("127.0.0.1", port, master_id)
    )
    await asyncio.sleep(0.15)  # tempo para o servidor bindar
    try:
        return await coro(port)
    finally:
        server_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server_task


def test_master_responde_alive():
    """DoD 1-3: Worker conecta, Master parseia HEARTBEAT, Worker recebe ALIVE."""
    async def cenario(port):
        return await worker_async.run_once(
            "127.0.0.1", port, master_uuid="Master_A", timeout=2.0
        )

    ok = asyncio.run(_com_master(9101, cenario))
    assert ok is True


def test_worker_detecta_timeout_sem_master():
    """DoD 4: sem Master no ar, o Worker não trava — retorna False rapidamente."""
    async def cenario():
        # Porta sem ninguém escutando -> ConnectionRefused -> False (rápido).
        return await worker_async.run_once(
            "127.0.0.1", 9199, master_uuid="Master_A", timeout=2.0
        )

    ok = asyncio.run(cenario())
    assert ok is False


def test_multiplos_heartbeats_mesma_sessao():
    """Vários heartbeats sequenciais continuam recebendo ALIVE (reconexão ok)."""
    async def cenario(port):
        resultados = []
        for _ in range(3):
            resultados.append(
                await worker_async.run_once(
                    "127.0.0.1", port, master_uuid="Master_A", timeout=2.0
                )
            )
        return resultados

    resultados = asyncio.run(_com_master(9102, cenario))
    assert resultados == [True, True, True]
