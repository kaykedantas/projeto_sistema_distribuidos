"""Teste de devolução do Worker emprestado (CT06)."""

import asyncio
import contextlib

from src.heartbeat import master_async, messaging, m2m


async def _sobe(name):
    m = master_async.Master("127.0.0.1", 0, master_id=name, name=name,
                            capacity=100, release_threshold=60)
    server = await asyncio.start_server(m.handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return m, server, port


async def _fecha(server):
    server.close()
    with contextlib.suppress(Exception):
        await server.wait_closed()


def test_ct06_devolucao_notifica_origem_e_remove_registro():
    async def cenario():
        # Master B (origem) recebe a notify_worker_returned
        b, sb, pb = await _sobe("MASTER_B")
        # Master A tem um worker emprestado registrado
        a, sa, pa = await _sobe("MASTER_KAYKE")
        a.borrowed_in["B1"] = {"origem": f"127.0.0.1:{pb}"}

        # devolve: notifica B (sem worker_writer real neste teste de unidade)
        await a.release_worker("B1", worker_writer=None,
                               origin_neighbor=("127.0.0.1", pb))
        await asyncio.sleep(0.1)

        removido_de_a = "B1" not in a.borrowed_in
        reintegrado_em_b = any(w.get("id") == "B1" for w in b.idle_workers)
        await _fecha(sa); await _fecha(sb)
        return removido_de_a, reintegrado_em_b

    removido, reintegrado = asyncio.run(cenario())
    assert removido is True
    assert reintegrado is True


def test_ct06_historese_evita_pingpong():
    """A carga entre release e capacity NÃO dispara nova devolução/empréstimo."""
    m = master_async.Master("127.0.0.1", 0, capacity=100, release_threshold=60)
    eventos = []
    m.on_saturation = lambda n: eventos.append("sat")
    m.on_release = lambda: eventos.append("rel")
    m.set_load(120)   # satura
    m.set_load(70)    # zona morta (60..100): nada
    m.set_load(90)    # ainda zona morta: nada
    assert eventos == ["sat"]
    m.set_load(40)    # abaixo de 60: libera
    assert eventos == ["sat", "rel"]
