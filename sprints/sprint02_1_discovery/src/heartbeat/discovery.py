"""
discovery.py — Descoberta dinâmica (UDP) e eleição determinística de Master.

A lógica (parsing/eleição) é mantida separada do transporte (datagram endpoint)
para permitir testes sem rede. O transporte usa ``asyncio`` e tem o **broadcast**
como padrão (mais robusto em LAN/WiFi); o **multicast** é opcional.

Etapas com log dedicado: DISCOVERY, ELECTION, CONNECTING (no worker), FALLBACK.

Payloads:
  Worker -> rede :  {"TYPE": "DISCOVERY", "WORKER_UUID": "..."}
  Master -> Worker: {"TYPE": "DISCOVERY_REPLY", "MASTER_NAME": "MASTER_X",
                     "MASTER_IP": "...", "MASTER_PORT": <int>, "STATUS": "AVAILABLE"}
"""

import asyncio
import logging
import re
import socket

from src.heartbeat import messaging

logger = logging.getLogger("discovery")

# Parâmetros padrão (Notas de Implementação do PDF).
DISC_PORT = 5000
MULTICAST_GROUP = "239.255.255.250"
BROADCAST_ADDR = "255.255.255.255"
COLLECT_WINDOW = 3.0  # janela fixa de coleta após o DISCOVERY
REQUIRED_REPLY = ("MASTER_NAME", "MASTER_IP", "MASTER_PORT")


def _natural_key(name):
    """Chave de ordenação natural: 'MASTER_10' -> ('master_', 10).

    Garante MASTER_1 < MASTER_2 < MASTER_10 (em vez da ordem puramente textual,
    onde '10' viria antes de '2').
    """
    m = re.match(r"^(.*?)(\d+)$", name or "")
    if m:
        return (m.group(1).lower(), int(m.group(2)))
    return ((name or "").lower(), -1)


def parse_reply(raw):
    """Valida uma ``DISCOVERY_REPLY``.

    Retorna o próprio dict se válido; ``None`` (com warning) se não for do tipo
    esperado ou se faltar um campo obrigatório (CT05 — strict parsing).
    """
    if not isinstance(raw, dict) or raw.get("TYPE") != "DISCOVERY_REPLY":
        return None
    for campo in REQUIRED_REPLY:
        if campo not in raw:
            logger.warning("DISCOVERY_REPLY descartada (faltou %s): %s", campo, raw)
            return None
    return raw


def elect_master(replies):
    """Aplica a regra determinística: menor MASTER_NAME (ordenação natural).

    Descarta replies inválidas e devolve o dict do Master eleito, ou ``None`` se
    não houver candidatos válidos.
    """
    validos = [r for r in (parse_reply(x) for x in replies) if r]
    if not validos:
        return None
    eleito = min(validos, key=lambda r: _natural_key(r["MASTER_NAME"]))
    logger.info("ELECTION: eleito %s entre %d candidato(s) válido(s)",
                eleito["MASTER_NAME"], len(validos))
    return eleito


# --------------------------------------------------------------------------- #
# Transporte UDP
# --------------------------------------------------------------------------- #

class DiscoveryProtocol(asyncio.DatagramProtocol):
    """Coleta DISCOVERY_REPLY recebidas durante a janela de descoberta."""

    def __init__(self):
        self.replies = []

    def datagram_received(self, data, addr):
        try:
            msg = messaging.decode_message(data)
        except Exception:  # noqa: BLE001 — datagrama corrompido não derruba a coleta
            logger.warning("Datagrama inválido de %s descartado", addr)
            return
        r = parse_reply(msg)
        if r:
            r.setdefault("_FROM", addr[0])
            self.replies.append(r)


async def discover(worker_uuid, *, disc_port=DISC_PORT, mode="broadcast",
                   group=MULTICAST_GROUP, window=COLLECT_WINDOW, target=None):
    """Envia um ``DISCOVERY`` e coleta respostas por ``window`` segundos.

    Parameters
    ----------
    mode:
        "broadcast" (padrão) envia para ``255.255.255.255:disc_port``;
        "multicast" envia para ``group:disc_port``.
    target:
        Destino unicast explícito ``(ip, porta)``. Usado em testes (loopback);
        quando definido, ignora ``mode``.
    """
    loop = asyncio.get_running_loop()
    transport, proto = await loop.create_datagram_endpoint(
        DiscoveryProtocol, family=socket.AF_INET, allow_broadcast=True,
        local_addr=("0.0.0.0", 0))
    try:
        if target is not None:
            dest = target
        elif mode == "multicast":
            dest = (group, disc_port)
        else:
            dest = (BROADCAST_ADDR, disc_port)
        pkt = messaging.encode_message({"TYPE": "DISCOVERY", "WORKER_UUID": worker_uuid})
        logger.info("DISCOVERY: enviando para %s (modo=%s)", dest, mode)
        transport.sendto(pkt, dest)
        await asyncio.sleep(window)  # janela fixa de coleta (Nota 3 do PDF)
        logger.info("DISCOVERY: coletada(s) %d resposta(s)", len(proto.replies))
        return list(proto.replies)
    finally:
        transport.close()
