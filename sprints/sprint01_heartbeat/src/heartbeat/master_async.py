"""
master_async.py — Nó Master (servidor TCP assíncrono) para a Sprint 01.

Responsabilidade nesta sprint: aceitar conexões de Workers, interpretar a
tarefa ``HEARTBEAT`` e responder imediatamente com ``RESPONSE: "ALIVE"``.

Usa ``asyncio`` para que o atendimento de um Heartbeat não bloqueie outras
operações — atendendo ao requisito de concorrência do backlog (Tarefa 04) e
preparando o terreno para as Sprints 02/03, em que o Master fala com vários
Workers e Masters ao mesmo tempo.

Payload de entrada  (Worker -> Master):  {"SERVER_UUID": "MASTER_KAYKE", "TASK": "HEARTBEAT"}
Payload de resposta (Master -> Worker):  {"SERVER_UUID": "MASTER_KAYKE", "TASK": "HEARTBEAT", "RESPONSE": "ALIVE"}
"""

import asyncio
import logging

from src.heartbeat import messaging

logger = logging.getLogger("master")


class Master:
    """Servidor Master assíncrono.

    Parameters
    ----------
    host, port:
        Endereço de escuta do socket TCP.
    master_id:
        Identificador único deste Master (vai no campo ``SERVER_UUID`` das
        respostas).
    """

    def __init__(self, host: str, port: int, master_id: str = "MASTER_KAYKE"):
        self.host = host
        self.port = port
        self.master_id = master_id
        self._server = None

    async def handle_client(self, reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter) -> None:
        """Trata uma conexão de Worker até que ela seja encerrada."""
        addr = writer.get_extra_info("peername")
        logger.info("Nova conexão de %s", addr)
        try:
            while True:
                msg = await messaging.read_message(reader)
                if msg is None:
                    break  # Worker encerrou a conexão

                # Strict parsing: ignoramos campos desconhecidos, mas o campo
                # obrigatório TASK precisa existir.
                task = msg.get("TASK")
                if task is None:
                    logger.warning("Mensagem sem campo obrigatório TASK: %s", msg)
                    continue

                if task == "HEARTBEAT":
                    logger.info("HEARTBEAT recebido de %s", addr)
                    response = {
                        "SERVER_UUID": self.master_id,
                        "TASK": "HEARTBEAT",
                        "RESPONSE": "ALIVE",
                    }
                    await messaging.send_message(writer, response)
                    logger.info("Resposta ALIVE enviada para %s", addr)
                else:
                    # type/TASK desconhecido: logar e ignorar, sem derrubar o processo.
                    logger.warning("TASK desconhecida ignorada: %r", task)
        except (ConnectionResetError, asyncio.IncompleteReadError):
            logger.info("Conexão com %s perdida", addr)
        except Exception:  # noqa: BLE001 — robustez: um cliente não derruba o Master
            logger.exception("Erro inesperado ao tratar %s", addr)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            logger.info("Conexão com %s encerrada", addr)

    async def start(self) -> None:
        """Sobe o servidor e bloqueia servindo para sempre."""
        self._server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        addrs = ", ".join(str(s.getsockname()) for s in self._server.sockets)
        logger.info("Master '%s' escutando em %s", self.master_id, addrs)
        async with self._server:
            await self._server.serve_forever()


async def run_server(host: str, port: int, master_id: str = "MASTER_KAYKE") -> None:
    """Atalho funcional usado pelos testes de integração."""
    await Master(host, port, master_id).start()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Master (servidor de Heartbeat)")
    parser.add_argument("--host", default="0.0.0.0", help="IP de escuta")
    parser.add_argument("--port", type=int, default=10000, help="Porta de escuta")
    parser.add_argument("--id", default="MASTER_KAYKE", help="master_id (SERVER_UUID)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    try:
        asyncio.run(run_server(args.host, args.port, args.id))
    except KeyboardInterrupt:
        logger.info("Master interrompido pelo usuário")


if __name__ == "__main__":
    main()
