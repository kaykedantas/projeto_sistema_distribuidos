"""
master_async.py — Nó Master (servidor TCP assíncrono).

Sprint 01 (Heartbeat): interpreta ``TASK: HEARTBEAT`` e responde ``ALIVE``.
Sprint 02 (Tarefas): mantém uma fila de tarefas e um registro de Workers, e
trata o ciclo de vida de uma tarefa:
  - Apresentação  (Worker -> Master):  {"WORKER": "ALIVE", "WORKER_UUID": "...",
                                         "SERVER_UUID": "..."(opcional)}
  - Entrega       (Master -> Worker):  {"TASK": "QUERY", "USER": "..."}  ou
                                       {"TASK": "NO_TASK"}
  - Reporte       (Worker -> Master):  {"STATUS": "OK|NOK", "TASK": "QUERY",
                                         "WORKER_UUID": "..."}
  - Confirmação   (Master -> Worker):  {"STATUS": "ACK", "WORKER_UUID": "..."}

Usa ``asyncio`` para atender vários Workers sem bloquear. Como o event loop é
single-thread, as operações sobre a fila/registro são atômicas entre corrotinas
(não há ``await`` no meio), dispensando locks.
"""

import asyncio
import logging
import socket
from collections import deque
from typing import Iterable, Optional

from src.heartbeat import messaging

logger = logging.getLogger("master")


def detect_outbound_ip() -> str:
    """Descobre o IP de saída desta máquina sem enviar pacote algum.

    Abre um socket UDP "discado" para um destino externo e lê o endereço local
    que o SO escolheria — útil para anunciar o MASTER_IP correto em LAN.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class Master:
    """Servidor Master assíncrono.

    Parameters
    ----------
    host, port:
        Endereço de escuta do socket TCP.
    master_id:
        Identificador único deste Master (vai no campo ``SERVER_UUID`` das
        respostas de heartbeat).
    tasks:
        Lista inicial de tarefas pendentes (cada item é o ``USER`` de uma
        ``QUERY``). Alimenta a fila do Master.
    """

    def __init__(self, host: str, port: int, master_id: str = "Master_A",
                 tasks: Optional[Iterable[str]] = None,
                 name: Optional[str] = None,
                 advertise_ip: Optional[str] = None):
        self.host = host
        self.port = port
        self.master_id = master_id
        # MASTER_NAME usado na descoberta/eleição (ex.: "MASTER_1"); default = id.
        self.name = name or master_id
        # IP anunciado nas DISCOVERY_REPLY (auto-detecta se não informado).
        self.advertise_ip = advertise_ip
        # Fila de tarefas pendentes (FIFO). Cada tarefa = nome de USER.
        self.tasks = deque(tasks or [])
        # Registro de Workers conhecidos:
        #   uuid -> {"emprestado": bool, "origem": str|None, "concluidas": int}
        self.workers = {}
        self._server = None
        # Transporte UDP de descoberta (preenchido por start_discovery()).
        self.disc_transport = None
        # Porta TCP anunciada na descoberta (default = self.port).
        self._advertised_tcp_port = port

    async def handle_client(self, reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter) -> None:
        """Trata uma conexão até que ela seja encerrada, despachando cada
        mensagem para o handler conforme seu tipo."""
        addr = writer.get_extra_info("peername")
        logger.info("Nova conexão de %s", addr)
        try:
            while True:
                msg = await messaging.read_message(reader)
                if msg is None:
                    break  # peer encerrou a conexão

                if not isinstance(msg, dict):
                    logger.warning("Mensagem não-objeto ignorada: %r", msg)
                    continue

                # Despacho por tipo (strict parsing: campos extras são ignorados).
                if msg.get("TASK") == "HEARTBEAT":
                    await self._handle_heartbeat(writer, addr)
                elif msg.get("WORKER") == "ALIVE":
                    await self._handle_apresentacao(msg, writer, addr)
                elif "STATUS" in msg:
                    await self._handle_status(msg, writer, addr)
                elif msg.get("TYPE") == "ELECTION_ACK":
                    await self._handle_election_ack(msg, writer, addr)
                else:
                    # Tipo desconhecido: logar e ignorar, sem derrubar o Master.
                    logger.warning("Mensagem não reconhecida ignorada: %s", msg)
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

    # ------------------------------------------------------------------ #
    # Handlers por tipo de mensagem
    # ------------------------------------------------------------------ #

    async def _handle_heartbeat(self, writer, addr) -> None:
        """Sprint 01: responde ALIVE a um HEARTBEAT."""
        logger.info("HEARTBEAT recebido de %s", addr)
        await messaging.send_message(writer, {
            "SERVER_UUID": self.master_id,
            "TASK": "HEARTBEAT",
            "RESPONSE": "ALIVE",
        })
        logger.info("Resposta ALIVE enviada para %s", addr)

    async def _handle_apresentacao(self, msg, writer, addr) -> None:
        """Sprint 02: apresentação do Worker -> entrega QUERY ou NO_TASK.

        Campos obrigatórios: WORKER, WORKER_UUID. Campo opcional SERVER_UUID
        indica que o Worker é "emprestado" (pertence a outro Master de origem).
        """
        uuid = msg.get("WORKER_UUID")
        if not uuid:  # strict parsing: obrigatório ausente -> falha controlada
            logger.warning("Apresentação sem WORKER_UUID ignorada: %s", msg)
            return

        origem = msg.get("SERVER_UUID")        # presente => emprestado
        emprestado = origem is not None
        self.workers.setdefault(uuid, {
            "emprestado": emprestado, "origem": origem, "concluidas": 0,
        })
        tipo = f"emprestado (origem {origem})" if emprestado else "local"
        logger.info("Apresentação de Worker %s [%s]", uuid, tipo)

        if self.tasks:
            user = self.tasks.popleft()        # atômico: sem await no meio
            logger.info("Entregando QUERY (USER=%s) ao Worker %s", user, uuid)
            await messaging.send_message(writer, {"TASK": "QUERY", "USER": user})
        else:
            logger.info("Fila vazia: NO_TASK para Worker %s", uuid)
            await messaging.send_message(writer, {"TASK": "NO_TASK"})

    async def _handle_status(self, msg, writer, addr) -> None:
        """Sprint 02: recebe o reporte de STATUS, registra (log) e devolve ACK."""
        uuid = msg.get("WORKER_UUID")
        status = msg.get("STATUS")
        if not uuid or status not in ("OK", "NOK"):
            logger.warning("Reporte de status inválido ignorado: %s", msg)
            return

        info = self.workers.setdefault(uuid, {
            "emprestado": False, "origem": None, "concluidas": 0,
        })
        info["concluidas"] += 1
        tipo = f"emprestado (origem {info['origem']})" if info["emprestado"] else "local"
        nivel = logger.info if status == "OK" else logger.warning
        nivel("Worker %s [%s] reportou %s na TASK %s (total concluídas: %d)",
              uuid, tipo, status, msg.get("TASK"), info["concluidas"])

        # ACK segue a "Definição do Payload Padrão" (com WORKER_UUID p/ correlação).
        await messaging.send_message(writer, {"STATUS": "ACK", "WORKER_UUID": uuid})

    async def _handle_election_ack(self, msg, writer, addr) -> None:
        """Sprint 2.1: recebe a confirmação de eleição do Worker e responde ACCEPTED."""
        sel = msg.get("SELECTED_MASTER")
        logger.info("ELECTION_ACK de %s (selecionado: %s)", msg.get("WORKER_UUID"), sel)
        await messaging.send_message(writer, {
            "TYPE": "ELECTION_ACK", "STATUS": "ACCEPTED", "MASTER_NAME": self.name,
        })

    # ------------------------------------------------------------------ #
    # Descoberta (responder UDP)
    # ------------------------------------------------------------------ #

    def _make_discovery_protocol(self):
        master = self

        class MasterDiscoveryProtocol(asyncio.DatagramProtocol):
            """Responde a um DISCOVERY via unicast ao IP de origem do Worker."""

            def connection_made(self, transport):
                self.tr = transport

            def datagram_received(self, data, addr):
                try:
                    msg = messaging.decode_message(data)
                except Exception:  # noqa: BLE001
                    logger.warning("DISCOVERY inválido de %s descartado", addr)
                    return
                if not isinstance(msg, dict) or msg.get("TYPE") != "DISCOVERY":
                    return
                ip = master.advertise_ip or detect_outbound_ip()
                reply = {
                    "TYPE": "DISCOVERY_REPLY",
                    "MASTER_NAME": master.name,
                    "MASTER_IP": ip,
                    "MASTER_PORT": master._advertised_tcp_port,
                    "STATUS": "AVAILABLE",
                }
                logger.info("DISCOVERY de %s (worker %s) -> respondendo %s",
                            addr, msg.get("WORKER_UUID"), master.name)
                self.tr.sendto(messaging.encode_message(reply), addr)

        return MasterDiscoveryProtocol

    async def start_discovery(self, disc_port: int = 5000,
                              tcp_port: Optional[int] = None) -> None:
        """Sobe o responder UDP de descoberta (em paralelo ao servidor TCP).

        ``tcp_port`` permite anunciar uma porta TCP diferente de ``self.port``
        (usado quando o servidor TCP roda em porta efêmera, p.ex. nos testes).
        """
        if tcp_port is not None:
            self._advertised_tcp_port = tcp_port
        loop = asyncio.get_running_loop()
        self.disc_transport, _ = await loop.create_datagram_endpoint(
            self._make_discovery_protocol(),
            local_addr=("0.0.0.0", disc_port),
            family=socket.AF_INET, allow_broadcast=True)
        bound = self.disc_transport.get_extra_info("sockname")
        logger.info("Master '%s' descoberta UDP escutando em %s", self.name, bound)

    def stop_discovery(self) -> None:
        if self.disc_transport is not None:
            self.disc_transport.close()
            self.disc_transport = None

    async def start(self) -> None:
        """Sobe o servidor e bloqueia servindo para sempre."""
        self._server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        addrs = ", ".join(str(s.getsockname()) for s in self._server.sockets)
        logger.info("Master '%s' escutando em %s", self.master_id, addrs)
        async with self._server:
            await self._server.serve_forever()


async def run_server(host: str, port: int, master_id: str = "Master_A",
                     tasks: Optional[Iterable[str]] = None,
                     name: Optional[str] = None,
                     advertise_ip: Optional[str] = None,
                     disc_port: Optional[int] = None) -> None:
    """Atalho funcional. Se ``disc_port`` for dado, sobe também o responder UDP."""
    m = Master(host, port, master_id, tasks=tasks, name=name,
               advertise_ip=advertise_ip)
    if disc_port is not None:
        await m.start_discovery(disc_port=disc_port, tcp_port=port)
    await m.start()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Master (descoberta + tarefas + heartbeat)")
    parser.add_argument("--host", default="0.0.0.0", help="IP de escuta TCP")
    parser.add_argument("--port", type=int, default=8000, help="Porta TCP")
    parser.add_argument("--id", default="Master_A", help="master_id (SERVER_UUID)")
    parser.add_argument("--name", default=None,
                        help="MASTER_NAME para descoberta/eleição (ex.: MASTER_1)")
    parser.add_argument("--advertise-ip", default=None,
                        help="IP anunciado nas DISCOVERY_REPLY (auto-detecta se omitido)")
    parser.add_argument("--disc-port", type=int, default=5000,
                        help="Porta UDP de descoberta (0 desativa)")
    parser.add_argument("--tasks", default="Michel,Julia",
                        help="Lista inicial de tarefas (USERs) separada por vírgula")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    tarefas = [t.strip() for t in args.tasks.split(",") if t.strip()]
    disc = args.disc_port if args.disc_port and args.disc_port > 0 else None
    try:
        asyncio.run(run_server(args.host, args.port, args.id, tasks=tarefas,
                               name=args.name, advertise_ip=args.advertise_ip,
                               disc_port=disc))
    except KeyboardInterrupt:
        logger.info("Master interrompido pelo usuário")


if __name__ == "__main__":
    main()
