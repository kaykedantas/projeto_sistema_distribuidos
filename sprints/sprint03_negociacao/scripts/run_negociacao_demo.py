#!/usr/bin/env python3
"""
run_negociacao_demo.py — Demo automática da Sprint 3 (negociação M2M).

Em um único processo (loopback): sobe Master B (com 2 workers ociosos) e Master
A. A satura via set_load, pede ajuda a B, recebe workers emprestados, um deles
se registra em A e executa uma tarefa; depois A normaliza a carga e devolve o
worker (notificando B).

Uso:
    python scripts/run_negociacao_demo.py
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.heartbeat import master_async, worker_async


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Master B com 2 workers ociosos; Master A com 1 tarefa na fila.
    b = master_async.Master("127.0.0.1", 0, master_id="MASTER_B", name="MASTER_B")
    b.idle_workers = [{"id": "B1", "address": "ip:1"}, {"id": "B2", "address": "ip:2"}]
    sb = await asyncio.start_server(b.handle_client, "127.0.0.1", 0)
    pb = sb.sockets[0].getsockname()[1]

    a = master_async.Master("127.0.0.1", 0, master_id="MASTER_KAYKE", name="MASTER_KAYKE",
                            tasks=["Michel"], capacity=100, release_threshold=60)
    sa = await asyncio.start_server(a.handle_client, "127.0.0.1", 0)
    pa = sa.sockets[0].getsockname()[1]
    a.neighbors["MASTER_B"] = ("127.0.0.1", pb)

    print(f">>> MASTER_KAYKE (TCP {pa}) e MASTER_B (TCP {pb}, 2 ociosos) no ar")

    # 1) A satura e pede ajuda
    a.set_load(150)
    print(">>> MASTER_KAYKE saturado (load=150 > capacity=100). Pedindo ajuda a B...")
    resp = await a.request_help_to("MASTER_B", workers_needed=1, timeout=2.0)
    print(f">>> Resposta de B: {resp['type']} "
          f"({resp['payload'].get('workers_offered', 0)} worker(s) ofertado(s))")
    wid = resp["payload"]["worker_details"][0]["id"]

    # 2) worker emprestado se registra em A e executa 1 tarefa
    await worker_async.register_as_temporary("127.0.0.1", pa, wid, f"127.0.0.1:{pb}")
    await asyncio.sleep(0.05)
    resultado = await worker_async.do_one_task("127.0.0.1", pa, wid,
                                               origin_master="MASTER_B")
    print(f">>> Worker emprestado {wid} executou tarefa em A: {resultado}")

    # 3) A normaliza e devolve o worker
    a.set_load(40)
    print(">>> MASTER_KAYKE normalizou (load=40 < release=60). Devolvendo worker...")
    await a.release_worker(wid, origin_neighbor=("127.0.0.1", pb))
    await asyncio.sleep(0.1)
    print(f">>> Devolvido. Em A borrowed_in={list(a.borrowed_in)} | "
          f"B reintegrou={[w['id'] for w in b.idle_workers]}")

    sa.close()
    sb.close()


if __name__ == "__main__":
    asyncio.run(main())
