"""
worker_async.py — Nó Worker (cliente TCP assíncrono) para a Sprint 01.

Responsabilidade nesta sprint: abrir conexão com o Master, enviar o payload
de ``HEARTBEAT`` em intervalos regulares (padrão: 10 s), aguardar a resposta
por no máximo 5 s (timeout do plano) e, ao receber ``ALIVE``, registrar isso
no log. Em caso de timeout/erro, tenta reconectar com backoff exponencial.

Payload de envio:  {"SERVER_UUID": "<master>", "TASK": "HEARTBEAT"}
"""

import asyncio
import logging

from src.heartbeat import messaging

logger = logging.getLogger("worker")

# Constantes derivadas do plano da Sprint 01.
HEARTBEAT_INTERVAL = 10.0  # segundos entre verificações
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


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Worker (cliente de Heartbeat)")
    parser.add_argument("--host", default="127.0.0.1", help="IP do Master")
    parser.add_argument("--port", type=int, default=10000, help="Porta do Master")
    parser.add_argument("--master", default="MASTER_KAYKE",
                        help="SERVER_UUID do Master alvo")
    parser.add_argument("--interval", type=float, default=HEARTBEAT_INTERVAL,
                        help="Intervalo entre heartbeats (s)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    try:
        asyncio.run(run_forever(args.host, args.port, args.master, args.interval))
    except KeyboardInterrupt:
        logger.info("Worker interrompido pelo usuário")


if __name__ == "__main__":
    main()
