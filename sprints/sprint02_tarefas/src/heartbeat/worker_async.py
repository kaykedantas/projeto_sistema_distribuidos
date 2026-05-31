"""
worker_async.py — Nó Worker (cliente TCP assíncrono).

Sprint 01 (Heartbeat): ``run_once`` / ``run_forever`` enviam HEARTBEAT e
aguardam ALIVE (mantidos).
Sprint 02 (Tarefas): loop de trabalho — o Worker se apresenta ao Master,
recebe uma QUERY (ou NO_TASK), simula o processamento, reporta o STATUS
(OK/NOK) e aguarda o ACK.

Payload de apresentação:  {"WORKER": "ALIVE", "WORKER_UUID": "...",
                            "SERVER_UUID": "..."(opcional, se emprestado)}
"""

import asyncio
import contextlib
import logging
import random

from src.heartbeat import messaging

logger = logging.getLogger("worker")

# Constantes derivadas do plano.
HEARTBEAT_INTERVAL = 10.0  # segundos entre heartbeats (Sprint 01)
RESPONSE_TIMEOUT = 5.0     # tempo máximo aguardando resposta do Master
BACKOFF_MAX = 8.0          # teto do backoff exponencial de reconexão


async def run_once(host: str, port: int, master_uuid: str,
                  timeout: float = RESPONSE_TIMEOUT) -> bool:
    """Executa um único ciclo de Heartbeat.

    Abre a conexão, envia o HEARTBEAT, aguarda a resposta com ``timeout`` e
    retorna ``True`` se o Master respondeu ``ALIVE``. Imprime/loga o resultado
    (requisito do DoD: "o Worker receber a confirmação ALIVE e imprimir isso
    no log").
    """
    writer = None
    try:
        reader, writer = await asyncio.open_connection(host, port)
        payload = {"SERVER_UUID": master_uuid, "TASK": "HEARTBEAT"}
        await messaging.send_message(writer, payload)
        logger.info("HEARTBEAT enviado para %s:%s", host, port)

        try:
            resp = await asyncio.wait_for(messaging.read_message(reader),
                                          timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Timeout (%.0fs) aguardando resposta do Master", timeout)
            return False

        if resp is not None and resp.get("RESPONSE") == "ALIVE":
            logger.info("Master %s respondeu ALIVE",
                        resp.get("SERVER_UUID", master_uuid))
            return True

        logger.warning("Resposta inesperada do Master: %s", resp)
        return False
    except (ConnectionRefusedError, OSError) as exc:
        logger.warning("Não foi possível conectar a %s:%s (%s)", host, port, exc)
        return False
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass


async def run_forever(host: str, port: int, master_uuid: str,
                     interval: float = HEARTBEAT_INTERVAL) -> None:
    """Loop infinito de Heartbeat com reconexão resiliente.

    Em sucesso, espera ``interval`` segundos até o próximo Heartbeat. Em falha,
    aplica backoff exponencial (1s, 2s, 4s, ... até ``BACKOFF_MAX``) antes de
    tentar de novo — sem travar o processo.
    """
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


# --------------------------------------------------------------------------- #
# Sprint 02 — ciclo de tarefas
# --------------------------------------------------------------------------- #

async def process_task(user, force=None, min_delay=0.05, max_delay=0.3):
    """Simula o processamento de uma QUERY e devolve ``"OK"`` ou ``"NOK"``.

    Faz um ``sleep`` curto para simular trabalho. ``force`` ("OK"/"NOK") torna
    o resultado determinístico (útil em testes); sem ele, falha ~10% das vezes.
    """
    await asyncio.sleep(random.uniform(min_delay, max_delay))
    if force in ("OK", "NOK"):
        return force
    return "OK" if random.random() > 0.1 else "NOK"


async def present(reader, writer, worker_uuid, origin_master=None):
    """Envia a apresentação (WORKER: ALIVE) e aguarda a resposta do Master."""
    payload = {"WORKER": "ALIVE", "WORKER_UUID": worker_uuid}
    if origin_master:                      # worker emprestado
        payload["SERVER_UUID"] = origin_master
    await messaging.send_message(writer, payload)
    return await asyncio.wait_for(messaging.read_message(reader),
                                  timeout=RESPONSE_TIMEOUT)


async def do_one_task(host, port, worker_uuid, origin_master=None):
    """Executa um ciclo completo numa conexão nova.

    present -> QUERY/NO_TASK -> (processa -> reporta STATUS -> aguarda ACK).
    Retorna "OK"/"NOK" (tarefa processada), "NO_TASK" (fila vazia) ou ``None``.
    """
    reader, writer = await asyncio.open_connection(host, port)
    try:
        resp = await present(reader, writer, worker_uuid, origin_master)
        if resp is None or resp.get("TASK") == "NO_TASK":
            logger.info("Sem tarefa no momento (NO_TASK)")
            return "NO_TASK"
        if resp.get("TASK") == "QUERY":
            user = resp.get("USER")
            logger.info("Recebeu QUERY (USER=%s); processando...", user)
            status = await process_task(user)
            await messaging.send_message(writer, {
                "STATUS": status, "TASK": "QUERY", "WORKER_UUID": worker_uuid})
            ack = await asyncio.wait_for(messaging.read_message(reader),
                                         timeout=RESPONSE_TIMEOUT)
            if ack and ack.get("STATUS") == "ACK":
                logger.info("ACK recebido — ciclo concluído (status: %s)", status)
            else:
                logger.warning("ACK não recebido como esperado: %s", ack)
            return status
        logger.warning("Resposta inesperada do Master: %s", resp)
        return None
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def work_loop(host, port, worker_uuid, origin_master=None, interval=2.0):
    """Loop contínuo de trabalho com reconexão resiliente.

    Após uma tarefa, recomeça quase imediatamente; em NO_TASK, espera
    ``interval`` (poll); em timeout/erro, aplica backoff exponencial.
    """
    backoff = 1.0
    while True:
        try:
            resultado = await do_one_task(host, port, worker_uuid, origin_master)
            backoff = 1.0
            await asyncio.sleep(interval if resultado == "NO_TASK" else 0.1)
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as exc:
            logger.warning("Falha (%s); reconectando em %.0fs", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Worker (cliente de tarefas/heartbeat)")
    parser.add_argument("--host", default="127.0.0.1", help="IP do Master")
    parser.add_argument("--port", type=int, default=8000, help="Porta do Master")
    parser.add_argument("--uuid", default="W-123", help="WORKER_UUID deste Worker")
    parser.add_argument("--origin-master", default=None,
                        help="SERVER_UUID do Master de origem (marca worker emprestado)")
    parser.add_argument("--mode", choices=["tasks", "heartbeat"], default="tasks",
                        help="tasks = ciclo de tarefas (Sprint 02); heartbeat = Sprint 01")
    parser.add_argument("--master", default="Master_A",
                        help="(modo heartbeat) SERVER_UUID do Master alvo")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    try:
        if args.mode == "heartbeat":
            asyncio.run(run_forever(args.host, args.port, args.master))
        else:
            asyncio.run(work_loop(args.host, args.port, args.uuid,
                                  origin_master=args.origin_master))
    except KeyboardInterrupt:
        logger.info("Worker interrompido pelo usuário")


if __name__ == "__main__":
    main()
