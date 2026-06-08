"""Testes do Master na Sprint 2.1: responder UDP e ELECTION_ACK no TCP."""

import asyncio
import contextlib

from src.heartbeat import master_async, messaging, discovery


def test_master_responde_discovery_reply():
    async def cenario():
        m = master_async.Master("127.0.0.1", 8000, master_id="MASTER_1",
                                 name="MASTER_1", advertise_ip="127.0.0.1")
        await m.start_discovery(disc_port=0)  # porta UDP efêmera
        port = m.disc_transport.get_extra_info("sockname")[1]
        try:
            achados = await discovery.discover("W-1", target=("127.0.0.1", port),
                                               window=0.5)
        finally:
            m.stop_discovery()
        return achados

    achados = asyncio.run(cenario())
    assert achados and achados[0]["MASTER_NAME"] == "MASTER_1"
    assert achados[0]["MASTER_PORT"] == 8000
    assert achados[0]["STATUS"] == "AVAILABLE"


def test_master_aceita_election_ack():
    async def cenario():
        m = master_async.Master("127.0.0.1", 0, master_id="MASTER_1", name="MASTER_1")
        server = await asyncio.start_server(m.handle_client, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await messaging.send_message(writer, {
            "TYPE": "ELECTION_ACK", "WORKER_UUID": "W-1", "SELECTED_MASTER": "MASTER_1"})
        resp = await asyncio.wait_for(messaging.read_message(reader), timeout=2)
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
        return resp

    resp = asyncio.run(cenario())
    assert resp["TYPE"] == "ELECTION_ACK"
    assert resp["STATUS"] == "ACCEPTED"
    assert resp["MASTER_NAME"] == "MASTER_1"
