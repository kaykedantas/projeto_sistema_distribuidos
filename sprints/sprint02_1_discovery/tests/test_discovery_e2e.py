"""Testes end-to-end da Sprint 2.1: descoberta → eleição → TCP → heartbeat,
e CT04 (queda do Master eleito após a conexão)."""

import asyncio
import contextlib

from src.heartbeat import master_async, worker_async, discovery


def test_e2e_descoberta_ate_heartbeat():  # CT01 ponta a ponta
    async def cenario():
        m = master_async.Master("127.0.0.1", 0, master_id="MASTER_1",
                                 name="MASTER_1", advertise_ip="127.0.0.1")
        server = await asyncio.start_server(m.handle_client, "127.0.0.1", 0)
        tcp_port = server.sockets[0].getsockname()[1]
        await m.start_discovery(disc_port=0, tcp_port=tcp_port)
        disc_port = m.disc_transport.get_extra_info("sockname")[1]
        async with server:
            replies = await discovery.discover("W-1", target=("127.0.0.1", disc_port),
                                               window=0.5)
            eleito = discovery.elect_master(replies)
            alvo = await worker_async.connect_and_confirm(eleito, "W-1")
            hb = await worker_async.run_once(alvo[0], alvo[1], "MASTER_1")
            m.stop_discovery()
            server.close()
        return eleito["MASTER_NAME"], alvo is not None, hb

    nome, conectou, hb = asyncio.run(cenario())
    assert nome == "MASTER_1"
    assert conectou is True
    assert hb is True


def test_ct04_queda_pos_eleicao_detectada():
    """Após confirmar a eleição, o Master cai; o Worker detecta a perda
    (run_once retorna False), o que no fluxo real dispara a re-descoberta."""
    async def cenario():
        m = master_async.Master("127.0.0.1", 0, master_id="MASTER_1",
                                 name="MASTER_1", advertise_ip="127.0.0.1")
        server = await asyncio.start_server(m.handle_client, "127.0.0.1", 0)
        tcp_port = server.sockets[0].getsockname()[1]
        master = {"MASTER_NAME": "MASTER_1", "MASTER_IP": "127.0.0.1",
                  "MASTER_PORT": tcp_port}
        alvo = await worker_async.connect_and_confirm(master, "W-1")
        # Master cai:
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
        # Próximo heartbeat ao alvo agora falha (conexão recusada):
        hb = await worker_async.run_once(alvo[0], alvo[1], "MASTER_1", timeout=1.0)
        return alvo is not None, hb

    confirmou, hb_apos_queda = asyncio.run(cenario())
    assert confirmou is True
    assert hb_apos_queda is False
