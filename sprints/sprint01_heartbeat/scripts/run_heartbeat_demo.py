#!/usr/bin/env python3
"""
run_heartbeat_demo.py — Demo automática: sobe um Master e dispara N heartbeats.

Tudo em um processo só, útil para validar rapidamente o fluxo da Sprint 01
sem abrir dois terminais.

Uso:
    python scripts/run_heartbeat_demo.py
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.heartbeat import master_async, worker_async

HOST, PORT, MASTER_ID = "127.0.0.1", 8765, "Master_A"


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    server = asyncio.create_task(
        master_async.run_server(HOST, PORT, MASTER_ID)
    )
    await asyncio.sleep(0.3)  # deixa o Master bindar

    for i in range(3):
        ok = await worker_async.run_once(HOST, PORT, MASTER_ID)
        print(f">>> Heartbeat {i + 1}: {'ALIVE' if ok else 'SEM RESPOSTA'}")
        await asyncio.sleep(1)

    server.cancel()


if __name__ == "__main__":
    asyncio.run(main())
