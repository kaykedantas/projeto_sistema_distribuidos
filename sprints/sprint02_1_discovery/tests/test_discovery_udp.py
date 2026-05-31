"""Testes do transporte UDP de descoberta sobre loopback (sem rede externa)."""

import asyncio

from src.heartbeat import discovery, messaging


class _FakeMaster(asyncio.DatagramProtocol):
    """Responder UDP de teste: devolve uma reply fixa à origem do datagrama."""

    def __init__(self, reply):
        self.reply = reply
        self.tr = None

    def connection_made(self, transport):
        self.tr = transport

    def datagram_received(self, data, addr):
        self.tr.sendto(messaging.encode_message(self.reply), addr)


async def _sobe_fake(reply):
    loop = asyncio.get_running_loop()
    tr, _ = await loop.create_datagram_endpoint(
        lambda: _FakeMaster(reply), local_addr=("127.0.0.1", 0))
    port = tr.get_extra_info("sockname")[1]
    return tr, port


def test_discover_coleta_uma_reply_loopback():  # CT01 (lado descoberta)
    reply = {"TYPE": "DISCOVERY_REPLY", "MASTER_NAME": "MASTER_1",
             "MASTER_IP": "127.0.0.1", "MASTER_PORT": 8000, "STATUS": "AVAILABLE"}

    async def cenario():
        tr, port = await _sobe_fake(reply)
        try:
            return await discovery.discover("W-1", target=("127.0.0.1", port),
                                            window=0.5)
        finally:
            tr.close()

    achados = asyncio.run(cenario())
    assert any(r["MASTER_NAME"] == "MASTER_1" for r in achados)


def test_discover_sem_resposta_retorna_vazio():  # CT03 (lado coleta)
    async def cenario():
        return await discovery.discover("W-1", target=("127.0.0.1", 59999),
                                        window=0.3)

    assert asyncio.run(cenario()) == []
