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
import contextlib
import logging
import socket
from collections import deque
from typing import Iterable, Optional

from src.heartbeat import messaging
from src.heartbeat import m2m

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

    def __init__(self, host: str, port: int, master_id: str = "MASTER_KAYKE",
                 tasks: Optional[Iterable[str]] = None,
                 name: Optional[str] = None,
                 advertise_ip: Optional[str] = None,
                 capacity: int = 100,
                 release_threshold: int = 60):
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

        # --- Sprint 3: estado de carga (com histerese) ---
        self.capacity = capacity                  # threshold de saturação
        self.release_threshold = release_threshold  # threshold de liberação (< capacity)
        self.current_load = 0
        self._saturated = False
        self.on_saturation = None  # callback(workers_needed) ao saturar
        self.on_release = None     # callback() ao normalizar a carga

        # --- Sprint 3: estado P2P Master-to-Master ---
        self.neighbors = {}        # master_id -> (ip, porta)
        self.idle_workers = []     # workers ociosos disponíveis p/ empréstimo
        self.borrowed_in = {}      # worker_id -> {"origem": addr}  (recebidos)
        self.lent_out = {}         # worker_id -> {"para": master_id} (cedidos)
        self.pending = {}          # request_id -> asyncio.Future (correlação)
        self.m2m_conns = {}        # master_id -> (reader, writer)  (pool)

    # ------------------------------------------------------------------ #
    # Sprint 3 — estado de carga e detecção de saturação (histerese)
    # ------------------------------------------------------------------ #

    def set_load(self, n: int) -> None:
        """Atualiza a carga atual e dispara saturação/liberação conforme limiares.

        Histerese: satura quando ``n > capacity``; só libera quando
        ``n < release_threshold`` (menor que capacity), evitando o efeito
        ping-pong de emprestar e devolver o mesmo Worker.
        """
        self.current_load = n
        if not self._saturated and n > self.capacity:
            self._saturated = True
            needed = self.compute_workers_needed(n)
            logger.info("SATURAÇÃO: load=%d > capacity=%d -> precisa de %d worker(s)",
                        n, self.capacity, needed)
            if self.on_saturation:
                self.on_saturation(needed)
        elif self._saturated and n < self.release_threshold:
            self._saturated = False
            logger.info("LIBERAÇÃO: load=%d < release=%d -> devolver emprestados",
                        n, self.release_threshold)
            if self.on_release:
                self.on_release()

    def compute_workers_needed(self, n: int) -> int:
        """Número de Workers a pedir, proporcional ao excedente sobre a capacity."""
        excedente = max(0, n - self.capacity)
        return max(1, excedente // max(1, self.capacity // 2))

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
                elif msg.get("type") in ("request_help", "response_accepted",
                                          "response_rejected", "register_temporary_worker",
                                          "notify_worker_returned"):
                    await self._handle_m2m(msg, reader, writer, addr)
                else:
                    # Tipo desconhecido: logar e ignorar, sem derrubar o Master (CT09).
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
    # Sprint 3 — negociação Master-to-Master
    # ------------------------------------------------------------------ #

    async def _handle_m2m(self, msg, reader, writer, addr) -> None:
        """Despacha mensagens M2M recebidas conforme o campo ``type``."""
        tipo = msg.get("type")
        rid = msg.get("request_id")
        logger.info("M2M <- %s | type=%s rid=%s", addr, tipo, rid)

        if tipo == "request_help":
            resposta = self.evaluate_help_request(msg.get("payload", {}), rid)
            await messaging.send_message(writer, resposta)
            logger.info("M2M -> %s | type=%s rid=%s", addr, resposta["type"], rid)
            # Se aceitou, dispara o redirecionamento dos workers ofertados.
            if resposta["type"] == "response_accepted":
                ofertados = resposta["payload"]["worker_details"]
                origem_addr = msg.get("payload", {}).get("master_id")
                await self._redirect_workers(ofertados, addr)

        elif tipo in ("response_accepted", "response_rejected"):
            fut = self.pending.get(rid)
            if fut and not fut.done():
                fut.set_result(msg)

        elif tipo == "register_temporary_worker":
            p = msg.get("payload", {})
            wid = p.get("worker_id")
            if not wid:
                logger.warning("register_temporary_worker sem worker_id: %s", msg)
                return
            self.borrowed_in[wid] = {"origem": p.get("original_master_address")}
            logger.info("Worker %s registrado como EMPRESTADO (origem %s) | "
                        "locais=%d emprestados=%d", wid, p.get("original_master_address"),
                        len(self.workers), len(self.borrowed_in))

        elif tipo == "notify_worker_returned":
            wid = msg.get("payload", {}).get("worker_id")
            self.lent_out.pop(wid, None)
            # readiciona à farm de ociosos (volta a poder emprestar/usar)
            if wid and all(w.get("id") != wid for w in self.idle_workers):
                self.idle_workers.append({"id": wid, "address": "?"})
            logger.info("Worker %s devolvido e reintegrado à farm de %s",
                        wid, self.name)

    def evaluate_help_request(self, payload, request_id):
        """Avalia um request_help e devolve response_accepted ou response_rejected
        (mantendo o mesmo ``request_id``)."""
        needed = int(payload.get("workers_needed", 0))
        if self._saturated:
            return m2m.response_rejected("high_load", request_id)
        if len(self.idle_workers) < needed or needed <= 0:
            if not self.idle_workers:
                return m2m.response_rejected("no_workers_available", request_id)
        # Separa até `needed` workers ociosos para ceder.
        ceder = self.idle_workers[:needed] if needed > 0 else []
        if not ceder:
            return m2m.response_rejected("no_workers_available", request_id)
        self.idle_workers = self.idle_workers[len(ceder):]
        for w in ceder:
            self.lent_out[w["id"]] = {"para": payload.get("master_id")}
        return m2m.response_accepted(ceder, request_id)

    async def _redirect_workers(self, worker_details, requester_addr) -> None:
        """Master ofertante: envia command_redirect a cada Worker ofertado.

        Nos testes/loopback os Workers são simulados; aqui registramos a intenção
        no log (a conexão real Master↔Worker da Sprint 02 é usada em produção).
        """
        for w in worker_details:
            logger.info("command_redirect -> Worker %s (novo master em %s)",
                        w.get("id"), requester_addr)

    async def request_help_to(self, neighbor_id, workers_needed, timeout=5.0):
        """Master solicitante: abre conexão com o vizinho, envia request_help e
        aguarda a resposta correlacionada por ``request_id`` (timeout em 5s)."""
        if neighbor_id not in self.neighbors:
            logger.warning("Vizinho %s desconhecido", neighbor_id)
            return None
        ip, port = self.neighbors[neighbor_id]
        msg = m2m.request_help(self.master_id, self.current_load,
                               self.capacity, workers_needed)
        rid = msg["request_id"]
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self.pending[rid] = fut
        leitor = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=timeout)
        except (asyncio.TimeoutError, OSError) as e:
            self.pending.pop(rid, None)
            logger.warning("request_help a %s falhou na conexão (%s)", neighbor_id, e)
            return None
        self.m2m_conns[neighbor_id] = (reader, writer)
        logger.info("M2M -> %s | type=request_help rid=%s", neighbor_id, rid)
        await messaging.send_message(writer, msg)

        async def _ler():
            while True:
                resp = await messaging.read_message(reader)
                if resp is None:
                    return
                if resp.get("request_id") == rid and not fut.done():
                    fut.set_result(resp)
                    return

        leitor = asyncio.create_task(_ler())
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("TIMEOUT (%.1fs) aguardando resposta de %s; libera rid=%s",
                           timeout, neighbor_id, rid)
            return None
        finally:
            self.pending.pop(rid, None)
            if leitor is not None:
                leitor.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await leitor
            # Evita conexões penduradas (DoD 9). O pool reutilizável fica como
            # melhoria futura; por ora fechamos a conexão após cada negociação.
            self.m2m_conns.pop(neighbor_id, None)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def release_worker(self, worker_id, worker_writer=None,
                             origin_neighbor=None):
        """Master saturado: devolve um Worker emprestado.

        Envia ``command_release`` ao Worker (se houver writer) e
        ``notify_worker_returned`` ao Master de origem. ``origin_neighbor`` é o
        ``(ip, porta)`` do Master de origem para a notificação M2M.
        """
        info = self.borrowed_in.pop(worker_id, None)
        origem = info["origem"] if info else None
        if worker_writer is not None:
            await messaging.send_message(worker_writer, m2m.command_release(origem))
            logger.info("command_release -> Worker %s (origem %s)", worker_id, origem)
        # Notifica o Master de origem (abre conexão própria; não depende do pool).
        target = origin_neighbor
        if target is None and origem:
            with contextlib.suppress(Exception):
                host, _, port = str(origem).rpartition(":")
                target = (host, int(port))
        if target is not None:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(*target), timeout=5.0)
                await messaging.send_message(writer, m2m.notify_worker_returned(worker_id))
                logger.info("notify_worker_returned -> %s (worker %s)", target, worker_id)
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
            except (asyncio.TimeoutError, OSError) as e:
                logger.warning("notify_worker_returned a %s falhou (%s)", target, e)


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


async def run_server(host: str, port: int, master_id: str = "MASTER_KAYKE",
                     tasks: Optional[Iterable[str]] = None,
                     name: Optional[str] = None,
                     advertise_ip: Optional[str] = None,
                     disc_port: Optional[int] = None,
                     neighbors: Optional[dict] = None,
                     capacity: int = 100,
                     release_threshold: int = 60,
                     idle_workers: Optional[list] = None) -> None:
    """Atalho funcional. Se ``disc_port`` for dado, sobe também o responder UDP."""
    m = Master(host, port, master_id, tasks=tasks, name=name,
               advertise_ip=advertise_ip, capacity=capacity,
               release_threshold=release_threshold)
    if neighbors:
        m.neighbors.update(neighbors)
    if idle_workers:
        m.idle_workers = list(idle_workers)

    # Wira o callback de saturação: ao saturar, pede ajuda a todos os vizinhos.
    if m.neighbors:
        def _on_saturation(workers_needed):
            loop = asyncio.get_event_loop()
            for nid in list(m.neighbors):
                loop.create_task(m.request_help_to(nid, workers_needed))

        def _on_release():
            pass  # devolução é feita explicitamente por release_worker

        m.on_saturation = _on_saturation
        m.on_release = _on_release

    if disc_port is not None:
        await m.start_discovery(disc_port=disc_port, tcp_port=port)
    await m.start()


def _parse_neighbors(spec):
    """Converte 'B@127.0.0.1:8001,C@127.0.0.1:8002' em {id: (ip, porta)}."""
    out = {}
    for item in (spec or "").split(","):
        item = item.strip()
        if not item:
            continue
        mid, _, addr = item.partition("@")
        host, _, port = addr.rpartition(":")
        out[mid] = (host, int(port))
    return out


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Master (negociação + descoberta + tarefas + heartbeat)")
    parser.add_argument("--host", default="0.0.0.0", help="IP de escuta TCP")
    parser.add_argument("--port", type=int, default=10000, help="Porta TCP")
    parser.add_argument("--id", default="MASTER_KAYKE", help="master_id (SERVER_UUID)")
    parser.add_argument("--name", default=None,
                        help="MASTER_NAME para descoberta/eleição (ex.: MASTER_1)")
    parser.add_argument("--advertise-ip", default=None,
                        help="IP anunciado nas DISCOVERY_REPLY (auto-detecta se omitido)")
    parser.add_argument("--disc-port", type=int, default=10000,
                        help="Porta UDP de descoberta (0 desativa)")
    parser.add_argument("--tasks", default="Michel,Julia",
                        help="Lista inicial de tarefas (USERs) separada por vírgula")
    parser.add_argument("--neighbors", default="",
                        help="Vizinhos M2M: 'B@127.0.0.1:8001,C@127.0.0.1:8002'")
    parser.add_argument("--capacity", type=int, default=100,
                        help="Threshold de saturação")
    parser.add_argument("--release-threshold", type=int, default=60,
                        help="Threshold de liberação (histerese; < capacity)")
    parser.add_argument("--idle-workers", default="",
                        help="Workers ociosos pré-registrados (ex: W1,W2,W3) — usados em M2M")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    tarefas = [t.strip() for t in args.tasks.split(",") if t.strip()]
    disc = args.disc_port if args.disc_port and args.disc_port > 0 else None
    vizinhos = _parse_neighbors(args.neighbors)
    ociosos = [{"id": w.strip(), "address": "?"} for w in args.idle_workers.split(",") if w.strip()]
    try:
        asyncio.run(run_server(args.host, args.port, args.id, tasks=tarefas,
                               name=args.name, advertise_ip=args.advertise_ip,
                               disc_port=disc, neighbors=vizinhos,
                               capacity=args.capacity,
                               release_threshold=args.release_threshold,
                               idle_workers=ociosos))
    except KeyboardInterrupt:
        logger.info("Master interrompido pelo usuário")


if __name__ == "__main__":
    main()
