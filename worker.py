"""
worker.py — Nó Worker unificado (Sprint 01 + 02 + 03).

Contém toda a lógica de messaging, M2M e discovery embutida neste único arquivo,
sem dependências externas além da biblioteca padrão do Python.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CONFIGURAÇÃO DE PORTAS — altere aqui para os testes em sala
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
# Pra rodar os worker : 
# python worker.py --name WORKER_A --id W-123 --port 8001 --master-host 127.0.0.1 --master-port 7011
# ================================================================
# CONFIGURAÇÃO RÁPIDA — altere estas variáveis para cada máquina
# ================================================================
DEFAULT_WORKER_UUID   = "W-123"      # UUID padrão deste Worker
DEFAULT_MASTER_HOST   = "127.0.0.1"  # IP do Master (modo fixo legado)
DEFAULT_MASTER_PORT   = 7011         # Porta TCP do Master (modo fixo legado)
DEFAULT_DISC_PORT     = 5000         # Porta UDP de descoberta (Sprint 2.1+)
DEFAULT_DISC_MODE     = "broadcast"  # "broadcast" ou "multicast"

HEARTBEAT_INTERVAL    = 10.0         # segundos entre heartbeats (Sprint 01)
RESPONSE_TIMEOUT      = 5.0          # tempo máximo aguardando resposta
BACKOFF_MAX           = 8.0          # teto do backoff exponencial
# ================================================================

import asyncio
import contextlib
import json
import logging
import random
import re
import socket
import uuid
from typing import Any, Optional, Union

logger = logging.getLogger("worker")


# ────────────────────────────────────────────────────────────────
# MÓDULO: messaging — serialização JSON sobre TCP (protocolo \n)
# ────────────────────────────────────────────────────────────────

MSG_DELIMITER = "\n"


def encode_message(obj: Any) -> bytes:
    """Serializa obj em JSON + delimitador \\n."""
    return (json.dumps(obj, ensure_ascii=False) + MSG_DELIMITER).encode("utf-8")


def decode_message(data: Union[bytes, str]) -> Any:
    """Converte linha JSON (com ou sem \\n) em objeto Python."""
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return json.loads(data.strip())


async def send_message(writer, obj: Any) -> None:
    """Escreve mensagem JSON delimitada por \\n no StreamWriter."""
    writer.write(encode_message(obj))
    await writer.drain()


async def read_message(reader) -> Optional[Any]:
    """Lê uma única mensagem (até \\n) do StreamReader. None = EOF."""
    line = await reader.readline()
    if not line:
        return None
    return decode_message(line)


# ────────────────────────────────────────────────────────────────
# MÓDULO: m2m — construtores das mensagens M2M usados pelo Worker
# ────────────────────────────────────────────────────────────────

def _new_request_id() -> str:
    return str(uuid.uuid4())


def _make_m2m_message(type_, payload, request_id=None):
    return {
        "type": type_,
        "request_id": request_id or _new_request_id(),
        "payload": payload or {},
    }


def m2m_register_temporary_worker(worker_id, original_master_address, request_id=None):
    return _make_m2m_message("register_temporary_worker", {
        "worker_id": worker_id,
        "original_master_address": original_master_address,
    }, request_id)


# ────────────────────────────────────────────────────────────────
# MÓDULO: discovery (lado cliente) — envia DISCOVERY e elege Master
# ────────────────────────────────────────────────────────────────

DISC_PORT_DEFAULT = DEFAULT_DISC_PORT
MULTICAST_GROUP   = "239.255.255.250"
BROADCAST_ADDR    = "255.255.255.255"
COLLECT_WINDOW    = 3.0
REQUIRED_REPLY    = ("MASTER_NAME", "MASTER_IP", "MASTER_PORT")


def _natural_key(name):
    """Ordenação natural: MASTER_1 < MASTER_2 < MASTER_10."""
    m = re.match(r"^(.*?)(\d+)$", name or "")
    if m:
        return (m.group(1).lower(), int(m.group(2)))
    return ((name or "").lower(), -1)


def parse_reply(raw):
    """Valida uma DISCOVERY_REPLY. Retorna o dict se válido, None se inválido."""
    if not isinstance(raw, dict) or raw.get("TYPE") != "DISCOVERY_REPLY":
        return None
    for campo in REQUIRED_REPLY:
        if campo not in raw:
            logger.warning("DISCOVERY_REPLY descartada (faltou %s): %s", campo, raw)
            return None
    return raw


def elect_master(replies):
    """Elege o Master de menor MASTER_NAME (ordenação natural). None se vazio."""
    validos = [r for r in (parse_reply(x) for x in replies) if r]
    if not validos:
        return None
    eleito = min(validos, key=lambda r: _natural_key(r["MASTER_NAME"]))
    logger.info("ELECTION: eleito %s entre %d candidato(s) válido(s)",
                eleito["MASTER_NAME"], len(validos))
    return eleito


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self):
        self.replies = []

    def datagram_received(self, data, addr):
        try:
            msg = decode_message(data)
        except Exception:
            logger.warning("Datagrama inválido de %s descartado", addr)
            return
        r = parse_reply(msg)
        if r:
            r.setdefault("_FROM", addr[0])
            self.replies.append(r)


async def discover(worker_uuid, *, disc_port=DISC_PORT_DEFAULT, mode=DEFAULT_DISC_MODE,
                   group=MULTICAST_GROUP, window=COLLECT_WINDOW, target=None):
    """Envia DISCOVERY UDP e coleta respostas durante a janela (window segundos).

    target: destino unicast explícito (ip, porta) — usado em testes/loopback.
    """
    loop = asyncio.get_running_loop()
    transport, proto = await loop.create_datagram_endpoint(
        _DiscoveryProtocol, family=socket.AF_INET, allow_broadcast=True,
        local_addr=("0.0.0.0", 0))
    try:
        if target is not None:
            dest = target
        elif mode == "multicast":
            dest = (group, disc_port)
        else:
            dest = (BROADCAST_ADDR, disc_port)
        pkt = encode_message({"TYPE": "DISCOVERY", "WORKER_UUID": worker_uuid})
        logger.info("DISCOVERY: enviando para %s (modo=%s)", dest, mode)
        transport.sendto(pkt, dest)
        await asyncio.sleep(window)
        logger.info("DISCOVERY: coletada(s) %d resposta(s)", len(proto.replies))
        return list(proto.replies)
    finally:
        transport.close()


# ────────────────────────────────────────────────────────────────
# Sprint 01 — Heartbeat
# ────────────────────────────────────────────────────────────────

def parse_address(addr):
    """Converte 'ip:porta' em (ip, int(porta))."""
    host, _, port = str(addr).rpartition(":")
    return host, int(port)


async def run_once(host: str, port: int, master_uuid: str,
                   timeout: float = RESPONSE_TIMEOUT) -> bool:
    """Executa um único ciclo de Heartbeat. Retorna True se Master respondeu ALIVE."""
    writer = None
    try:
        reader, writer = await asyncio.open_connection(host, port)
        payload = {"SERVER_UUID": master_uuid, "TASK": "HEARTBEAT"}
        await send_message(writer, payload)
        logger.info("HEARTBEAT enviado para %s:%s", host, port)

        try:
            resp = await asyncio.wait_for(read_message(reader), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Timeout (%.0fs) aguardando resposta do Master", timeout)
            return False

        if resp is not None and resp.get("RESPONSE") == "ALIVE":
            logger.info("Master %s respondeu ALIVE", resp.get("SERVER_UUID", master_uuid))
            return True

        logger.warning("Resposta inesperada do Master: %s", resp)
        return False
    except (ConnectionRefusedError, OSError) as exc:
        logger.warning("Não foi possível conectar a %s:%s (%s)", host, port, exc)
        return False
    finally:
        if writer is not None:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()


async def run_forever(host: str, port: int, master_uuid: str,
                      interval: float = HEARTBEAT_INTERVAL) -> None:
    """Loop infinito de Heartbeat com reconexão resiliente (backoff exponencial)."""
    backoff = 1.0
    while True:
        ok = await run_once(host, port, master_uuid)
        if ok:
            backoff = 1.0
            await asyncio.sleep(interval)
        else:
            logger.info("Tentando reconectar em %.0fs...", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)


# ────────────────────────────────────────────────────────────────
# Sprint 02 — ciclo de tarefas (QUERY / NO_TASK / STATUS / ACK)
# ────────────────────────────────────────────────────────────────

async def process_task(user, force=None, min_delay=0.05, max_delay=0.3):
    """Simula processamento de uma QUERY. Retorna "OK" ou "NOK" (~10% falha)."""
    logger.debug("Processando tarefa USER=%s", user)
    await asyncio.sleep(random.uniform(min_delay, max_delay))
    if force in ("OK", "NOK"):
        return force
    return "OK" if random.random() > 0.1 else "NOK"


async def present(reader, writer, worker_uuid, origin_master=None):
    """Envia a apresentação WORKER:ALIVE e aguarda a resposta do Master."""
    payload = {"WORKER": "ALIVE", "WORKER_UUID": worker_uuid}
    if origin_master:
        payload["SERVER_UUID"] = origin_master
    await send_message(writer, payload)
    return await asyncio.wait_for(read_message(reader), timeout=RESPONSE_TIMEOUT)


async def do_one_task(host, port, worker_uuid, origin_master=None):
    """Executa um ciclo completo: present → QUERY/NO_TASK/command_redirect/command_release.

    Retorna uma 4-tupla (code, new_host, new_port, new_origin):
      - code: "OK"|"NOK"|"NO_TASK"|"REDIRECTED"|"RELEASED"|None
      - new_host, new_port, new_origin: conexão a usar no próximo ciclo
        (inalterada na maioria dos casos; atualizada em REDIRECTED/RELEASED)
    """
    reader, writer = await asyncio.open_connection(host, port)
    try:
        resp = await present(reader, writer, worker_uuid, origin_master)
        if resp is None or resp.get("TASK") == "NO_TASK":
            logger.info("Sem tarefa no momento (NO_TASK)")
            return "NO_TASK", host, port, origin_master
        if resp.get("TASK") == "QUERY":
            user = resp.get("USER")
            logger.info("Recebeu QUERY (USER=%s); processando...", user)
            status = await process_task(user)
            await send_message(writer, {
                "STATUS": status, "TASK": "QUERY", "WORKER_UUID": worker_uuid})
            ack = await asyncio.wait_for(read_message(reader), timeout=RESPONSE_TIMEOUT)
            if ack and ack.get("STATUS") == "ACK":
                logger.info("ACK recebido — ciclo concluído (status: %s)", status)
            else:
                logger.warning("ACK não recebido como esperado: %s", ack)
            return status, host, port, origin_master
        # Sprint 3.1: comandos M2M enviados pelo master na resposta à apresentação
        msg_type = resp.get("type") if isinstance(resp, dict) else None
        if msg_type == "command_redirect":
            new_addr = resp.get("payload", {}).get("new_master_address", "")
            new_host, new_port = parse_address(new_addr)
            cur_origin = origin_master or f"{host}:{port}"
            logger.info("command_redirect recebido -> novo master %s:%s", new_host, new_port)
            await register_as_temporary(new_host, new_port, worker_uuid, cur_origin)
            return "REDIRECTED", new_host, new_port, cur_origin
        if msg_type == "command_release":
            orig_addr = resp.get("payload", {}).get("original_master_address", "")
            orig_host, orig_port = parse_address(orig_addr)
            logger.info("command_release recebido -> retornando a %s:%s", orig_host, orig_port)
            return "RELEASED", orig_host, orig_port, None
        logger.warning("Resposta inesperada do Master: %s", resp)
        return None, host, port, origin_master
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def work_loop(host, port, worker_uuid, origin_master=None, interval=2.0):
    """Loop contínuo de trabalho com reconexão resiliente.

    Mantém o estado de conexão atual (host, port, origin) e atualiza-o
    automaticamente ao receber command_redirect ou command_release.
    """
    backoff = 1.0
    cur_host, cur_port, cur_origin = host, port, origin_master
    while True:
        try:
            res, cur_host, cur_port, cur_origin = await do_one_task(
                cur_host, cur_port, worker_uuid, cur_origin)
            backoff = 1.0
            if res == "NO_TASK":
                await asyncio.sleep(interval)
            elif res in ("REDIRECTED", "RELEASED"):
                logger.info("Conexão atualizada: %s:%s (origin=%s)",
                            cur_host, cur_port, cur_origin)
                await asyncio.sleep(0.5)
            else:
                await asyncio.sleep(0.1)
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as exc:
            logger.warning("Falha (%s); reconectando em %.0fs", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)


# ────────────────────────────────────────────────────────────────
# Sprint 2.1 — descoberta, eleição e handshake
# ────────────────────────────────────────────────────────────────

async def connect_and_confirm(master, worker_uuid):
    """Abre TCP com o Master eleito, envia ELECTION_ACK e aguarda ACCEPTED.

    Retorna (host, port) em sucesso ou None em falha.
    """
    host, port = master["MASTER_IP"], master["MASTER_PORT"]
    logger.info("CONNECTING: TCP %s:%s (master %s)", host, port, master["MASTER_NAME"])
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=RESPONSE_TIMEOUT)
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as exc:
        logger.warning("CONNECTING falhou (%s)", exc)
        return None
    try:
        await send_message(writer, {
            "TYPE": "ELECTION_ACK", "WORKER_UUID": worker_uuid,
            "SELECTED_MASTER": master["MASTER_NAME"]})
        ack = await asyncio.wait_for(read_message(reader), timeout=RESPONSE_TIMEOUT)
        if ack and ack.get("STATUS") == "ACCEPTED":
            logger.info("Eleição confirmada por %s", ack.get("MASTER_NAME"))
            return (host, port)
        logger.warning("ELECTION_ACK inesperado: %s", ack)
        return None
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as exc:
        logger.warning("Handshake de eleição falhou (%s)", exc)
        return None
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def bootstrap(worker_uuid, *, mode=DEFAULT_DISC_MODE, disc_port=DISC_PORT_DEFAULT,
                    window=COLLECT_WINDOW, max_attempts=None, base_backoff=1.0,
                    home_master=None):
    """Descobre, elege e confirma um Master. Retorna (host, port) ou None.

    home_master: se informado, conecta SOMENTE ao master com esse MASTER_NAME,
                 ignorando todos os outros descobertos. Repete até encontrá-lo.
                 Sem home_master, usa a eleição normal (menor MASTER_NAME).
    """
    backoff = base_backoff
    tentativa = 0
    while max_attempts is None or tentativa < max_attempts:
        tentativa += 1
        replies = await discover(worker_uuid, mode=mode, disc_port=disc_port, window=window)

        if home_master:
            filtrados = [r for r in replies if r.get("MASTER_NAME") == home_master]
            if not filtrados:
                encontrados = [r.get("MASTER_NAME") for r in replies]
                logger.warning(
                    "Master '%s' nao encontrado (tentativa %d) — encontrados: %s — FALLBACK em %.1fs",
                    home_master, tentativa, encontrados or "nenhum", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)
                continue
            eleito = filtrados[0]
            logger.info("HOME_MASTER: conectando a '%s' (%s:%s)",
                        home_master, eleito.get("MASTER_IP"), eleito.get("MASTER_PORT"))
        else:
            eleito = elect_master(replies)
            if eleito is None:
                logger.warning("NO_MASTER_FOUND (tentativa %d) — FALLBACK em %.1fs",
                               tentativa, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)
                continue

        alvo = await connect_and_confirm(eleito, worker_uuid)
        if alvo:
            return alvo
        logger.warning("FALLBACK: conexão pós-eleição falhou; refaz descoberta")
        backoff = base_backoff
    return None


# ────────────────────────────────────────────────────────────────
# Sprint 03 — redirecionamento e devolução de Workers
# ────────────────────────────────────────────────────────────────

async def register_as_temporary(host, port, worker_id, original_master_address):
    """Worker emprestado: conecta ao novo Master e envia register_temporary_worker.

    Retorna True se envio ocorreu com sucesso.
    """
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=RESPONSE_TIMEOUT)
    except (asyncio.TimeoutError, OSError) as e:
        logger.warning("register_temporary_worker: conexão a %s:%s falhou (%s)",
                       host, port, e)
        return False
    try:
        await send_message(writer, m2m_register_temporary_worker(
            worker_id, original_master_address))
        logger.info("register_temporary_worker enviado a %s:%s (worker %s, origem %s)",
                    host, port, worker_id, original_master_address)
        return True
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def handle_command_redirect(msg, worker_id, current_origin=None):
    """Trata command_redirect: registra-se no novo Master.

    Retorna (host, port) do novo Master.
    """
    new_addr = msg.get("payload", {}).get("new_master_address")
    host, port = parse_address(new_addr)
    logger.info("command_redirect recebido -> novo master %s", new_addr)
    await register_as_temporary(host, port, worker_id, current_origin or "?")
    return host, port


async def handle_command_release(msg):
    """Trata command_release: retorna ao Master de origem.

    Retorna (host, port) do Master de origem.
    """
    origin = msg.get("payload", {}).get("original_master_address")
    host, port = parse_address(origin)
    logger.info("command_release recebido -> retornando ao master de origem %s", origin)
    return host, port


# ────────────────────────────────────────────────────────────────
# Ponto de entrada — main()
# ────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Worker — Sprint 01 (Heartbeat) + 02 (Tarefas) + 03 (Redirecionamento)")
    parser.add_argument("--uuid", default=DEFAULT_WORKER_UUID,
                        help=f"WORKER_UUID deste Worker (padrão: {DEFAULT_WORKER_UUID})")
    parser.add_argument("--discovery-mode", choices=["broadcast", "multicast"],
                        default=DEFAULT_DISC_MODE,
                        help=f"Transporte UDP de descoberta (padrão: {DEFAULT_DISC_MODE})")
    parser.add_argument("--disc-port", type=int, default=DEFAULT_DISC_PORT,
                        help=f"Porta UDP de descoberta (padrão: {DEFAULT_DISC_PORT})")
    parser.add_argument("--home-master", default=None,
                        help="MASTER_NAME do seu master (ex.: MASTER_B). O worker conecta "
                             "somente a esse master via discovery, ignorando os demais.")
    parser.add_argument("--origin-master", default=None,
                        help="SERVER_UUID do Master de origem (marca worker emprestado)")
    # Modo legado (Sprint 01/02): alvo fixo, sem descoberta
    parser.add_argument("--host", default=DEFAULT_MASTER_HOST,
                        help=f"(legado) IP fixo do Master (padrão: {DEFAULT_MASTER_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_MASTER_PORT,
                        help=f"(legado) Porta fixa do Master (padrão: {DEFAULT_MASTER_PORT})")
    parser.add_argument("--mode", choices=["discovery", "tasks", "heartbeat"],
                        default="discovery",
                        help="discovery = Sprint 2.1 (padrão); tasks/heartbeat = alvo fixo")
    parser.add_argument("--master", default="Master_A",
                        help="(modo heartbeat) SERVER_UUID do Master alvo")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    async def run_discovery():
        if args.home_master:
            print(f"\nWorker {args.uuid} — procurando master '{args.home_master}' "
                  f"via discovery (porta UDP {args.disc_port})...\n")
        else:
            print(f"\nWorker {args.uuid} — discovery UDP (porta {args.disc_port}), "
                  f"eleicao por menor MASTER_NAME...\n")
        alvo = await bootstrap(args.uuid, mode=args.discovery_mode,
                               disc_port=args.disc_port,
                               home_master=args.home_master)
        if alvo is None:
            logger.error("Não foi possível eleger um Master; encerrando.")
            return
        host, port = alvo
        logger.info("Iniciando ciclo de trabalho com Master em %s:%s", host, port)
        await work_loop(host, port, args.uuid, origin_master=args.origin_master)

    try:
        if args.mode == "heartbeat":
            asyncio.run(run_forever(args.host, args.port, args.master))
        elif args.mode == "tasks":
            asyncio.run(work_loop(args.host, args.port, args.uuid,
                                  origin_master=args.origin_master))
        else:  # discovery (padrão Sprint 2.1+)
            asyncio.run(run_discovery())
    except KeyboardInterrupt:
        logger.info("Worker interrompido pelo usuário")


if __name__ == "__main__":
    main()
