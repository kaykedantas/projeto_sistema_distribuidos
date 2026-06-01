#!/usr/bin/env python3
"""
run_tarefas_demo.py — Demo automática do ciclo de tarefas da Sprint 02.

Sobe um Master com a fila ["Michel", "Julia"], roda o Worker por alguns ciclos
e mostra QUERY -> processamento -> STATUS -> ACK, e depois NO_TASK quando a fila
esvazia.

Uso:
    python scripts/run_tarefas_demo.py
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.heartbeat import master_async, worker_async

HOST, PORT = "127.0.0.1", 8770


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    m = master_async.Master(HOST, PORT, master_id="MASTER_KAYKE",
                            tasks=["Michel", "Julia"])
    server = asyncio.create_task(m.start())
    await asyncio.sleep(0.3)

    # 3 ciclos: 2 com tarefa (Michel, Julia) e 1 com a fila já vazia (NO_TASK).
    for i in range(3):
        resultado = await worker_async.do_one_task(HOST, PORT, "W-123")
        print(f">>> Ciclo {i + 1}: resultado = {resultado}")
        await asyncio.sleep(0.4)

    print(">>> Registro final de workers no Master:", m.workers)
    server.cancel()


if __name__ == "__main__":
    asyncio.run(main())
