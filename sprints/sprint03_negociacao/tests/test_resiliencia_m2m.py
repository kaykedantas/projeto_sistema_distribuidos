"""Testes de resiliência M2M: type desconhecido (CT09) e queda do receptor (CT08)."""

import asyncio
import contextlib

from src.heartbeat import master_async, messaging, m2m


async def _sobe(name, ociosos=0):
    m = master_async.Master("127.0.0.1", 0, master_id=name, name=name)
    m.idle_workers = [{"id": f"{name}{i}", "address": f"ip:{i}"} for i in range(ociosos)]
    server = await asyncio.start_server(m.handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return m, server, port


async def _fecha(server):
    server.close()
    with contextlib.suppress(Exception):
        await server.wait_closed()


def test_ct09_tipo_desconhecido_e_ignorado_sem_derrubar():
    async def cenario():
        b, sb, pb = await _sobe("B", ociosos=1)
        reader, writer = await asyncio.open_connection("127.0.0.1", pb)
        # 1) envia type desconhecido
        await messaging.send_message(writer, {"type": "tipo_inexistente",
                                              "request_id": "x", "payload": {}})
        await asyncio.sleep(0.1)
        # 2) na MESMA conexão, envia um request_help válido e espera resposta
        await messaging.send_message(writer, m2m.request_help("A", 150, 100, 1,
                                                              request_id="r-ok"))
        resp = await asyncio.wait_for(messaging.read_message(reader), timeout=2)
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        await _fecha(sb)
        return resp

    resp = asyncio.run(cenario())
    # O Master ignorou o desconhecido e continuou operando, respondendo ao válido.
    assert resp["request_id"] == "r-ok"
    assert resp["type"] in ("response_accepted", "response_rejected")


def test_ct08_worker_emprestado_detecta_queda_do_receptor():
    """Worker operando sob A; A cai -> próxima tarefa falha (dispara retorno a B)."""
    from src.heartbeat import worker_async

    async def cenario():
        a, sa, pa = await _sobe("MASTER_A")
        # worker emprestado faz um ciclo com sucesso
        await worker_async.register_as_temporary("127.0.0.1", pa, "B1", "127.0.0.1:9000")
        # A cai:
        await _fecha(sa)
        # próxima operação do worker contra A falha (detecção da queda)
        ok = await worker_async.run_once("127.0.0.1", pa, "MASTER_A", timeout=1.0)
        return ok

    assert asyncio.run(cenario()) is False
