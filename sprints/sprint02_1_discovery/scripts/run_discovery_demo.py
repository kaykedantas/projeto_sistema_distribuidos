#!/usr/bin/env python3
"""
run_discovery_demo.py — Demo automática da Sprint 2.1 (descoberta + eleição).

Em um único processo: sobe um Master (UDP responder + TCP) chamado MASTER_1,
faz o Worker descobrir via loopback, eleger, confirmar a eleição (ELECTION_ACK
-> ACCEPTED) e executar o primeiro Heartbeat. Em seguida demonstra o caminho
NO_MASTER_FOUND (porta sem responder).

Uso:
    python scripts/run_discovery_demo.py
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.heartbeat import master_async, worker_async, discovery


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # 1) Sobe Master (TCP efêmero + responder UDP) chamado MASTER_1.
    m = master_async.Master("127.0.0.1", 0, master_id="MASTER_1",
                            name="MASTER_1", advertise_ip="127.0.0.1")
    server = await asyncio.start_server(m.handle_client, "127.0.0.1", 0)
    tcp_port = server.sockets[0].getsockname()[1]
    await m.start_discovery(disc_port=0, tcp_port=tcp_port)
    disc_port = m.disc_transport.get_extra_info("sockname")[1]

    print(f">>> MASTER_1 no ar (TCP {tcp_port}, descoberta UDP {disc_port})")

    # 2) Worker descobre -> elege -> confirma -> heartbeat.
    replies = await discovery.discover("W-101", target=("127.0.0.1", disc_port),
                                       window=0.5)
    print(f">>> DISCOVERY: {len(replies)} resposta(s)")
    eleito = discovery.elect_master(replies)
    print(f">>> ELECTION: eleito {eleito['MASTER_NAME']}")
    alvo = await worker_async.connect_and_confirm(eleito, "W-101")
    print(f">>> CONNECTING: eleição confirmada, alvo TCP = {alvo}")
    hb = await worker_async.run_once(alvo[0], alvo[1], "MASTER_1")
    print(f">>> HEARTBEAT inicial: {'ALIVE' if hb else 'sem resposta'}")

    m.stop_discovery()
    server.close()

    # 3) Caminho NO_MASTER_FOUND: descoberta numa porta sem ninguém.
    print(">>> Demonstrando NO_MASTER_FOUND (porta sem Master)...")
    vazio = await discovery.discover("W-101", target=("127.0.0.1", 59999),
                                     window=0.3)
    print(f">>> DISCOVERY: {len(vazio)} resposta(s) -> "
          f"{'NO_MASTER_FOUND (aplicaria backoff)' if not vazio else 'achou'}")


if __name__ == "__main__":
    asyncio.run(main())
