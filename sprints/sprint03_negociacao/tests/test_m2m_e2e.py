"""E2E da Sprint 3: ciclo completo de empréstimo e devolução entre Masters."""

import asyncio
import contextlib

from src.heartbeat import master_async, worker_async, messaging, m2m


async def _sobe(name, ociosos=0, tasks=None):
    m = master_async.Master("127.0.0.1", 0, master_id=name, name=name, tasks=tasks,
                            capacity=100, release_threshold=60)
    m.idle_workers = [{"id": f"{name}{i}", "address": f"ip:{i}"} for i in range(ociosos)]
    server = await asyncio.start_server(m.handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return m, server, port


async def _fecha(server):
    server.close()
    with contextlib.suppress(Exception):
        await server.wait_closed()


def test_e2e_emprestimo_tarefa_e_devolucao():
    """A satura -> pede a B -> accepted -> worker registra em A (emprestado) ->
    A entrega QUERY -> OK -> ACK -> A normaliza -> devolução (notify a B)."""
    async def cenario():
        b, sb, pb = await _sobe("MASTER_B", ociosos=2)
        a, sa, pa = await _sobe("MASTER_A", tasks=["Michel"])
        a.neighbors["MASTER_B"] = ("127.0.0.1", pb)

        # 1) A satura e pede ajuda a B
        a.set_load(150)
        resp = await a.request_help_to("MASTER_B", workers_needed=1, timeout=2.0)
        assert resp["type"] == "response_accepted"
        emprestado_id = resp["payload"]["worker_details"][0]["id"]

        # 2) o worker ofertado se registra em A como emprestado e executa 1 tarefa
        await worker_async.register_as_temporary(
            "127.0.0.1", pa, emprestado_id, f"127.0.0.1:{pb}")
        await asyncio.sleep(0.05)
        resultado = await worker_async.do_one_task(
            "127.0.0.1", pa, emprestado_id, origin_master="MASTER_B")

        # 3) A normaliza a carga e devolve o worker (notifica B)
        a.set_load(40)
        await a.release_worker(emprestado_id, origin_neighbor=("127.0.0.1", pb))
        await asyncio.sleep(0.1)

        registrado_durante = a.workers.get(emprestado_id, {}).get("emprestado")
        devolvido = emprestado_id not in a.borrowed_in
        b_reintegrou = any(w.get("id") == emprestado_id for w in b.idle_workers)

        await _fecha(sa); await _fecha(sb)
        return resp["type"], resultado, registrado_durante, devolvido, b_reintegrou

    tipo, resultado, emprestado, devolvido, reintegrou = asyncio.run(cenario())
    assert tipo == "response_accepted"
    assert resultado in ("OK", "NOK")
    assert emprestado is True
    assert devolvido is True
    assert reintegrou is True
