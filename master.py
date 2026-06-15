"""
master.py — Nó Master unificado (Sprint 01 + 02 + 03).

Contém toda a lógica de messaging, M2M e discovery embutida neste único arquivo,
sem dependências externas além da biblioteca padrão do Python.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CONFIGURAÇÃO DE PORTAS — altere aqui para os testes em sala
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

# ================================================================
# CONFIGURAÇÃO RÁPIDA — altere estas variáveis para cada máquina
# ================================================================
DEFAULT_HOST          = "0.0.0.0"    # IP de escuta TCP (0.0.0.0 = todas as interfaces)
DEFAULT_TCP_PORT      = 7011         # Porta TCP deste Master
DEFAULT_DISC_PORT     = 5000         # Porta UDP de descoberta (0 = desativada)
DEFAULT_MASTER_ID     = "MASTER_9"   # Identificador único deste Master (o --name deriva disso)
DEFAULT_TASKS         = "Michel,Julia"  # Tarefas iniciais separadas por vírgula
DEFAULT_CAPACITY      = 4      # Limiar de saturação (Sprint 3 — histerese)
DEFAULT_RELEASE_THRESHOLD = 2       # Limiar de liberação (DEVE ser < capacity)
DEFAULT_MAX_TASK_ATTEMPTS = 3        # tentativas por tarefa antes de descartar (NOK)
# Vizinhos M2M — exemplo: "MASTER_B@192.168.1.10:8001,MASTER_C@192.168.1.11:8001"
# TROQUE IP_DO_AMIGO pelo IP da máquina do vizinho (e o nome MASTER_B se ele usar outro).
DEFAULT_NEIGHBORS     = "10.189.36.154:7011"
# 
#
# 
# ================================================================
#Pra rodar o master : 
# python master.py --name MASTER_A --id MASTER_A --port 7011 --disc-port 5000 --capacity 1 --neighbors "MASTER_B@127.0.0.1:7012"
# python master.py --name MASTER_A --id MASTER_A --port 7011 --disc-port 5000 --capacity 1 --neighbors "MASTER_B@26.108.248.191:7011"
import asyncio
import contextlib
import json
import logging
import re
import socket
import sys
import uuid
from collections import deque
from typing import Any, Iterable, Optional, Union

logger = logging.getLogger("master")


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
# MÓDULO: m2m — construtores das mensagens Master-to-Master (Sprint 3)
# ────────────────────────────────────────────────────────────────

M2M_REASONS = {"high_load", "no_workers_available", "refused"}


def new_request_id() -> str:
    return str(uuid.uuid4())


def make_m2m_message(type_, payload, request_id=None):
    return {
        "type": type_,
        "request_id": request_id or new_request_id(),
        "payload": payload or {},
    }


def m2m_request_help(master_id, current_load, capacity, workers_needed,
                     master_address=None, request_id=None):
    payload = {
        "master_id": master_id,
        "current_load": current_load,
        "capacity": capacity,
        "workers_needed": workers_needed,
    }
    if master_address:
        payload["master_address"] = master_address  # extensão: endereço TCP do solicitante
    return make_m2m_message("request_help", payload, request_id)


def m2m_response_accepted(worker_details, request_id=None):
    return make_m2m_message("response_accepted", {
        "workers_offered": len(worker_details),
        "worker_details": worker_details,
    }, request_id)


def m2m_response_rejected(reason, request_id=None):
    return make_m2m_message("response_rejected", {"reason": reason}, request_id)


def m2m_command_redirect(new_master_address, request_id=None):
    return make_m2m_message("command_redirect",
                            {"new_master_address": new_master_address}, request_id)


def m2m_register_temporary_worker(worker_id, original_master_address, request_id=None):
    return make_m2m_message("register_temporary_worker", {
        "worker_id": worker_id,
        "original_master_address": original_master_address,
    }, request_id)


def m2m_command_release(original_master_address, request_id=None):
    return make_m2m_message("command_release",
                            {"original_master_address": original_master_address}, request_id)


def m2m_notify_worker_returned(worker_id, request_id=None):
    return make_m2m_message("notify_worker_returned", {"worker_id": worker_id}, request_id)


# ────────────────────────────────────────────────────────────────
# MÓDULO: discovery (lado servidor) — responde a DISCOVERY UDP
# ────────────────────────────────────────────────────────────────

DISC_PORT         = DEFAULT_DISC_PORT
MULTICAST_GROUP   = "239.255.255.250"
BROADCAST_ADDR    = "255.255.255.255"


def detect_outbound_ip() -> str:
    """Descobre o IP de saída desta máquina sem enviar pacote algum."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


# ────────────────────────────────────────────────────────────────
# CLASSE PRINCIPAL: Master
# ────────────────────────────────────────────────────────────────

class Master:
    """Servidor Master assíncrono — Sprint 01 (Heartbeat) + 02 (Tarefas) + 03 (Negociação).

    Sprint 01: responde HEARTBEAT → ALIVE
    Sprint 02: mantém fila FIFO de tarefas, ciclo QUERY/NO_TASK/STATUS/ACK
    Sprint 03: load tracking com histerese, negociação M2M, discovery UDP
    """

    def __init__(self,
                 host: str = DEFAULT_HOST,
                 port: int = DEFAULT_TCP_PORT,
                 master_id: str = DEFAULT_MASTER_ID,
                 tasks: Optional[Iterable[str]] = None,
                 name: Optional[str] = None,
                 advertise_ip: Optional[str] = None,
                 capacity: int = DEFAULT_CAPACITY,
                 release_threshold: int = DEFAULT_RELEASE_THRESHOLD,
                 max_task_attempts: int = DEFAULT_MAX_TASK_ATTEMPTS):
        self.host = host
        self.port = port
        self.master_id = master_id
        self.name = name or master_id
        self.advertise_ip = advertise_ip

        # Fila de tarefas pendentes (FIFO). Cada tarefa = nome de USER.
        self.tasks = deque(tasks or [])
        # Registro de Workers: uuid -> {emprestado, origem, concluidas}
        self.workers = {}
        self._server = None

        # Tolerância a falhas de tarefa (entrega at-least-once):
        #   in_flight     : worker_uuid -> user (tarefa entregue e ainda NÃO confirmada; p/ observabilidade)
        #   task_attempts : user -> nº de tentativas já feitas (limite de retentativa por NOK)
        #   A autoridade do reenfileiramento on-disconnect é o `ctx` por conexão (ver handle_client),
        #   evitando corrida quando o mesmo UUID reconecta antes do EOF da conexão antiga ser tratado.
        self.in_flight = {}
        self.task_attempts = {}
        self.max_task_attempts = max_task_attempts

        # Discovery UDP
        self.disc_transport = None
        self._advertised_tcp_port = port
        self._disc_port = 0  # atualizado por start_discovery()

        # Sprint 3: estado de carga com histerese
        self.capacity = capacity
        self.release_threshold = release_threshold
        self.current_load = 0
        self._saturated = False
        self.on_saturation = None   # callback(workers_needed)
        self.on_release = None      # callback()

        # Sprint 3: estado P2P Master-to-Master
        self.neighbors = {}         # master_id -> (ip, porta)
        self.idle_workers = []      # workers ociosos para empréstimo
        self.borrowed_in = {}       # worker_id -> {"origem": addr}
        self.lent_out = {}          # worker_id -> {"para": master_id}
        self.pending = {}           # request_id -> asyncio.Future
        self.m2m_conns = {}         # master_id -> (reader, writer)

        # Sprint 3.1: filas de comandos M2M pendentes (entregues na próxima apresentação)
        self.pending_redirects = {}  # worker_id -> new_master_address (string "ip:porta")
        self.pending_releases  = {}  # worker_id -> original_master_address

        # Carga inicial a partir das tarefas pré-carregadas (sem disparar callbacks ainda)
        self.current_load = len(self.tasks)

    # ── Sprint 3: histerese de carga ────────────────────────────

    def set_load(self, n: int) -> None:
        """Atualiza carga e dispara callbacks de saturação/liberação."""
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
        excedente = max(0, n - self.capacity)
        return max(1, excedente // max(1, self.capacity // 2))

    # ── Conexão TCP principal ────────────────────────────────────

    async def handle_client(self, reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.info("Nova conexão de %s", addr)
        # Tarefa em andamento NESTA conexão (autoridade do reenfileiramento on-disconnect).
        ctx = {"uuid": None, "task": None}
        try:
            while True:
                msg = await read_message(reader)
                if msg is None:
                    break

                if not isinstance(msg, dict):
                    logger.warning("Mensagem não-objeto ignorada: %r", msg)
                    continue

                if msg.get("TASK") == "HEARTBEAT":
                    await self._handle_heartbeat(writer, addr)
                elif msg.get("WORKER") == "ALIVE":
                    await self._handle_apresentacao(msg, writer, addr, ctx)
                elif "STATUS" in msg:
                    await self._handle_status(msg, writer, addr, ctx)
                elif msg.get("TYPE") == "ELECTION_ACK":
                    await self._handle_election_ack(msg, writer, addr)
                elif msg.get("type") in ("request_help", "response_accepted",
                                          "response_rejected", "register_temporary_worker",
                                          "notify_worker_returned"):
                    await self._handle_m2m(msg, reader, writer, addr)
                else:
                    logger.warning("Mensagem não reconhecida ignorada: %s", msg)
        except (ConnectionResetError, asyncio.IncompleteReadError):
            logger.info("Conexão com %s perdida", addr)
        except Exception:
            logger.exception("Erro inesperado ao tratar %s", addr)
        finally:
            # Se o worker caiu com uma tarefa em andamento, devolve-a à fila (at-least-once).
            self._requeue_if_inflight(ctx)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            logger.info("Conexão com %s encerrada", addr)

    # ── Handlers por tipo de mensagem ───────────────────────────

    async def _handle_heartbeat(self, writer, addr) -> None:
        """Sprint 01: responde ALIVE a um HEARTBEAT."""
        logger.info("HEARTBEAT recebido de %s", addr)
        await send_message(writer, {
            "SERVER_UUID": self.master_id,
            "TASK": "HEARTBEAT",
            "RESPONSE": "ALIVE",
        })
        logger.info("Resposta ALIVE enviada para %s", addr)

    async def _handle_apresentacao(self, msg, writer, addr, ctx=None) -> None:
        """Sprint 02: apresentação do Worker -> entrega QUERY ou NO_TASK.
        Sprint 3.1: verifica comandos M2M pendentes antes de servir tarefas.
        Tolerância a falhas: registra a tarefa entregue em `ctx` (por conexão) para
        permitir reenfileiramento caso o Worker caia antes de reportar STATUS."""
        uuid_ = msg.get("WORKER_UUID")
        if not uuid_:
            logger.warning("Apresentação sem WORKER_UUID ignorada: %s", msg)
            return

        origem = msg.get("SERVER_UUID")
        emprestado = origem is not None
        self.workers.setdefault(uuid_, {
            "emprestado": emprestado, "origem": origem, "concluidas": 0,
        })
        tipo = f"emprestado (origem {origem})" if emprestado else "local"
        logger.info("Apresentação de Worker %s [%s]", uuid_, tipo)

        # command_release tem prioridade: devolve worker emprestado ao master de origem
        if uuid_ in self.pending_releases:
            orig = self.pending_releases.pop(uuid_)
            self.borrowed_in.pop(uuid_, None)
            await send_message(writer, m2m_command_release(orig))
            logger.info("command_release -> Worker %s (origem %s)", uuid_, orig)
            return

        # command_redirect: redireciona worker ocioso para master saturado
        if uuid_ in self.pending_redirects:
            new_addr = self.pending_redirects.pop(uuid_)
            self.idle_workers = [w for w in self.idle_workers if w.get("id") != uuid_]
            await send_message(writer, m2m_command_redirect(new_addr))
            logger.info("command_redirect -> Worker %s -> %s", uuid_, new_addr)
            return

        if self.tasks:
            user = self.tasks.popleft()
            if ctx is not None:                 # marca tarefa em andamento nesta conexão
                ctx["uuid"] = uuid_
                ctx["task"] = user
            self.in_flight[uuid_] = user        # espelho p/ observabilidade (/workers)
            self.set_load(len(self.tasks))  # atualiza carga após retirar tarefa
            logger.info("Entregando QUERY (USER=%s) ao Worker %s", user, uuid_)
            await send_message(writer, {"TASK": "QUERY", "USER": user})
        else:
            # Worker local ocioso: adicionar à farm de empréstimo
            if not emprestado and all(w.get("id") != uuid_ for w in self.idle_workers):
                self.idle_workers.append({"id": uuid_, "address": f"{addr[0]}:{addr[1]}"})
                logger.info("Worker %s adicionado aos ociosos (total: %d)",
                            uuid_, len(self.idle_workers))
            logger.info("Fila vazia: NO_TASK para Worker %s", uuid_)
            await send_message(writer, {"TASK": "NO_TASK"})

    async def _handle_status(self, msg, writer, addr, ctx=None) -> None:
        """Sprint 02: recebe STATUS, registra e devolve ACK.
        Tolerância a falhas: confirma a tarefa em andamento (OK) ou reenfileira (NOK)
        respeitando o limite de tentativas."""
        uuid_ = msg.get("WORKER_UUID")
        status = msg.get("STATUS")
        if not uuid_ or status not in ("OK", "NOK"):
            logger.warning("Reporte de status inválido ignorado: %s", msg)
            return

        info = self.workers.setdefault(uuid_, {
            "emprestado": False, "origem": None, "concluidas": 0,
        })
        info["concluidas"] += 1

        # Consome a tarefa em andamento desta conexão (se houver).
        user = None
        if ctx is not None and ctx.get("uuid") == uuid_:
            user = ctx.get("task")
            ctx["task"] = None
        self.in_flight.pop(uuid_, None)

        if status == "OK":
            if user is not None:
                self.task_attempts.pop(user, None)  # tarefa concluída: zera tentativas
        else:  # NOK -> retentar com limite (dead-letter ao exceder)
            if user is not None:
                self._requeue_task(user, motivo="NOK")

        tipo = f"emprestado (origem {info['origem']})" if info["emprestado"] else "local"
        nivel = logger.info if status == "OK" else logger.warning
        nivel("Worker %s [%s] reportou %s na TASK %s (total: %d)",
              uuid_, tipo, status, msg.get("TASK"), info["concluidas"])
        await send_message(writer, {"STATUS": "ACK", "WORKER_UUID": uuid_})

    # ── Tolerância a falhas de tarefa (reenfileiramento) ─────────

    def _requeue_if_inflight(self, ctx) -> None:
        """Worker caiu com tarefa em andamento -> devolve à fila.

        Falha de infraestrutura (queda de conexão) NÃO consome tentativa: a tarefa
        nunca chegou a ser processada por completo, então volta para nova entrega.
        """
        user = ctx.get("task") if ctx else None
        if user is None:
            return
        ctx["task"] = None
        self.in_flight.pop(ctx.get("uuid"), None)
        self.tasks.appendleft(user)
        self.set_load(len(self.tasks))
        logger.warning("Worker %s caiu com TASK '%s' em andamento -> reenfileirada (fila=%d)",
                       ctx.get("uuid"), user, len(self.tasks))

    def _requeue_task(self, user, motivo="") -> None:
        """Reenfileira por NOK respeitando o limite de tentativas (dead-letter ao exceder).

        Obs.: as tentativas são contadas por nome de tarefa (USER); tarefas com nomes
        idênticos compartilham o contador — suficiente para a simulação deste projeto.
        """
        attempts = self.task_attempts.get(user, 0) + 1
        if attempts < self.max_task_attempts:
            self.task_attempts[user] = attempts
            self.tasks.appendleft(user)
            self.set_load(len(self.tasks))
            logger.warning("%s em '%s' (tentativa %d/%d) -> reenfileirada (fila=%d)",
                           motivo, user, attempts, self.max_task_attempts, len(self.tasks))
        else:
            self.task_attempts.pop(user, None)
            logger.error("'%s' excedeu %d tentativas (%s) -> descartada (dead-letter)",
                         user, self.max_task_attempts, motivo)

    async def _handle_election_ack(self, msg, writer, addr) -> None:
        """Sprint 2.1: recebe confirmação de eleição do Worker e responde ACCEPTED."""
        sel = msg.get("SELECTED_MASTER")
        logger.info("ELECTION_ACK de %s (selecionado: %s)", msg.get("WORKER_UUID"), sel)
        await send_message(writer, {
            "TYPE": "ELECTION_ACK", "STATUS": "ACCEPTED", "MASTER_NAME": self.name,
        })

    # ── Sprint 3: negociação M2M ─────────────────────────────────

    async def _handle_m2m(self, msg, reader, writer, addr) -> None:
        tipo = msg.get("type")
        rid = msg.get("request_id")
        logger.info("M2M <- %s | type=%s rid=%s", addr, tipo, rid)

        if tipo == "request_help":
            resposta = self.evaluate_help_request(msg.get("payload", {}), rid)
            await send_message(writer, resposta)
            logger.info("M2M -> %s | type=%s rid=%s", addr, resposta["type"], rid)
            if resposta["type"] == "response_accepted":
                ofertados = resposta["payload"]["worker_details"]
                # Usa o endereço declarado pelo master solicitante (contém a porta TCP correta)
                requester_addr = msg.get("payload", {}).get("master_address",
                                 f"{addr[0]}:{self.port}")
                await self._redirect_workers(ofertados, requester_addr)

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
            if wid and all(w.get("id") != wid for w in self.idle_workers):
                self.idle_workers.append({"id": wid, "address": "?"})
            logger.info("Worker %s devolvido e reintegrado à farm de %s",
                        wid, self.name)

    def evaluate_help_request(self, payload, request_id):
        """Avalia request_help e devolve response_accepted ou response_rejected."""
        needed = int(payload.get("workers_needed", 0))
        if self._saturated:
            return m2m_response_rejected("high_load", request_id)
        if not self.idle_workers:
            return m2m_response_rejected("no_workers_available", request_id)
        ceder = self.idle_workers[:needed] if needed > 0 else []
        if not ceder:
            return m2m_response_rejected("no_workers_available", request_id)
        self.idle_workers = self.idle_workers[len(ceder):]
        for w in ceder:
            self.lent_out[w["id"]] = {"para": payload.get("master_id")}
        return m2m_response_accepted(ceder, request_id)

    async def _redirect_workers(self, worker_details, new_master_address) -> None:
        """Popula pending_redirects; o comando é enviado na próxima apresentação do Worker."""
        for w in worker_details:
            wid = w.get("id")
            self.pending_redirects[wid] = str(new_master_address)
            logger.info("Redirecionamento pendente: Worker %s -> %s", wid, new_master_address)

    async def request_help_to(self, neighbor_id, workers_needed, timeout=5.0):
        """Abre conexão com vizinho, envia request_help e aguarda resposta (timeout 5s)."""
        if neighbor_id not in self.neighbors:
            logger.warning("Vizinho %s desconhecido", neighbor_id)
            return None
        ip, port = self.neighbors[neighbor_id]
        # Inclui o endereço de escuta deste master para que o vizinho saiba onde redirecionar
        master_addr = f"{self.advertise_ip or detect_outbound_ip()}:{self.port}"
        msg = m2m_request_help(self.master_id, self.current_load,
                               self.capacity, workers_needed,
                               master_address=master_addr)
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
        await send_message(writer, msg)

        async def _ler():
            while True:
                resp = await read_message(reader)
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
            self.m2m_conns.pop(neighbor_id, None)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def release_worker(self, worker_id, worker_writer=None,
                             origin_neighbor=None):
        """Devolve um Worker emprestado: envia command_release e notifica o Master de origem."""
        info = self.borrowed_in.pop(worker_id, None)
        origem = info["origem"] if info else None
        if worker_writer is not None:
            await send_message(worker_writer, m2m_command_release(origem))
            logger.info("command_release -> Worker %s (origem %s)", worker_id, origem)
        target = origin_neighbor
        if target is None and origem:
            with contextlib.suppress(Exception):
                host, _, port = str(origem).rpartition(":")
                target = (host, int(port))
        if target is not None:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(*target), timeout=5.0)
                await send_message(writer, m2m_notify_worker_returned(worker_id))
                logger.info("notify_worker_returned -> %s (worker %s)", target, worker_id)
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
            except (asyncio.TimeoutError, OSError) as e:
                logger.warning("notify_worker_returned a %s falhou (%s)", target, e)

    async def _notify_origin_returned(self, worker_id: str, origem_addr: str) -> None:
        """Notifica o master de origem (via TCP) que o worker emprestado foi devolvido."""
        try:
            host, _, port_s = str(origem_addr).rpartition(":")
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, int(port_s)), timeout=5.0)
            await send_message(writer, m2m_notify_worker_returned(worker_id))
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            logger.info("notify_worker_returned -> %s (worker %s)", origem_addr, worker_id)
        except (asyncio.TimeoutError, OSError) as e:
            logger.warning("notify_worker_returned a %s falhou (%s)", origem_addr, e)

    # ── Discovery UDP (Sprint 2.1 / 3) ──────────────────────────

    def _make_discovery_protocol(self):
        master = self

        class MasterDiscoveryProtocol(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.tr = transport

            def datagram_received(self, data, addr):
                try:
                    msg = decode_message(data)
                except Exception:
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
                self.tr.sendto(encode_message(reply), addr)

        return MasterDiscoveryProtocol

    async def _try_connect_neighbor(self, neighbor_id: str) -> bool:
        """Tenta conexão TCP rápida ao vizinho. Retorna True se alcançável."""
        if neighbor_id not in self.neighbors:
            return False
        ip, port = self.neighbors[neighbor_id]
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=2.0)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            return True
        except (asyncio.TimeoutError, OSError):
            return False

    async def _print_startup_banner(self) -> None:
        """Exibe o banner de inicialização com IP, portas, thresholds e status dos vizinhos."""
        ip = self.advertise_ip or detect_outbound_ip()
        disc_info = str(self._disc_port) if self._disc_port else "desativada"
        sep = "=" * 56

        print(f"\n{sep}")
        print(f"  Master {self.name} ({self.master_id}) Online")
        print(sep)
        print(f"  IP: {ip}  |  TCP: {self.port}  |  UDP discovery: {disc_info}")
        print(f"  Saturacao: >{self.capacity} tarefas  |  Liberacao: <{self.release_threshold} tarefas")
        print(f"  Tarefas na fila: {len(self.tasks)}  |  Workers ociosos: {len(self.idle_workers)}")

        if self.neighbors:
            print(f"  Vizinhos:")
            algum_alcancavel = False
            for nid, (nip, nport) in self.neighbors.items():
                alcancavel = await self._try_connect_neighbor(nid)
                if alcancavel:
                    algum_alcancavel = True
                status = "[ALCANCAVEL]" if alcancavel else "[NAO ENCONTRADO]"
                print(f"    {nid} @ {nip}:{nport}  {status}")
            # Dica: para emprestar workers o master vizinho precisa ter workers ociosos
            if algum_alcancavel and len(self.tasks) > self.capacity:
                print(f"  >> Saturado! Pedindo ajuda aos vizinhos alcancaveis...")
        else:
            print(f"  Vizinhos: nenhum configurado")

        # Dica de como conectar workers a este master para emprestimo
        if self.neighbors and not self.tasks:
            print(f"  >> Para disponibilizar workers para emprestimo, rode:")
            print(f"     python worker.py --mode tasks --host {ip} --port {self.port} --uuid W-1")

        print(sep)
        print(f"  Aguardando conexoes...\n")

    async def _stdin_task_feeder(self) -> None:
        """Lê tarefas do stdin em tempo real enquanto o servidor roda.

        Digite o nome de uma tarefa e pressione Enter para adicioná-la à fila.
        Comandos especiais:
          /fila      — mostra quantas tarefas estão pendentes
          /workers   — mostra workers conectados e ociosos
          /sair      — encerra o master
        """
        loop = asyncio.get_running_loop()
        print("  Modo interativo: digite tarefas e pressione Enter.")
        print("  Comandos: /fila  /workers  /sair\n")
        while True:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
            except Exception:
                break
            if not line:   # EOF (Ctrl+D / pipe fechado)
                break
            cmd = line.strip()
            if not cmd:
                continue
            if cmd == "/sair":
                print("  Master encerrando...")
                self._server.close()
                break
            if cmd == "/fila":
                print(f"  Fila: {len(self.tasks)} tarefa(s) pendente(s): {list(self.tasks)}")
                continue
            if cmd == "/workers":
                print(f"  Workers locais   : {len(self.workers)}")
                print(f"  Workers ociosos  : {len(self.idle_workers)} {self.idle_workers}")
                print(f"  Workers recebidos: {len(self.borrowed_in)} {list(self.borrowed_in)}")
                print(f"  Tarefas em andamento: {len(self.in_flight)} {self.in_flight}")
                continue
            # Qualquer outra entrada é tratada como nome de tarefa
            self.tasks.append(cmd)
            self.set_load(len(self.tasks))
            print(f"  [+] Tarefa '{cmd}' adicionada — fila: {len(self.tasks)} tarefa(s)")

    async def start_discovery(self, disc_port: int = DEFAULT_DISC_PORT,
                              tcp_port: Optional[int] = None) -> None:
        """Sobe o responder UDP de descoberta em paralelo ao servidor TCP."""
        if tcp_port is not None:
            self._advertised_tcp_port = tcp_port
        self._disc_port = disc_port
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
        """Sobe o servidor TCP, exibe o banner e fica servindo para sempre."""
        self._server = await asyncio.start_server(
            self.handle_client, self.host, self.port)
        # Atualiza self.port com a porta real (quando port=0 o SO escolhe uma efêmera)
        actual_port = self._server.sockets[0].getsockname()[1]
        if self.port == 0:
            self.port = actual_port
            self._advertised_tcp_port = actual_port
        addrs = ", ".join(str(s.getsockname()) for s in self._server.sockets)
        logger.info("Master '%s' escutando em %s", self.master_id, addrs)
        # Verifica carga inicial: dispara on_saturation se já saturado ao iniciar
        if self.tasks:
            self.set_load(len(self.tasks))
        await self._print_startup_banner()
        async with self._server:
            await asyncio.gather(
                self._server.serve_forever(),
                self._stdin_task_feeder(),
            )


# ────────────────────────────────────────────────────────────────
# Funções auxiliares de inicialização
# ────────────────────────────────────────────────────────────────

def _setup_auto_callbacks(m: "Master") -> None:
    """Conecta os callbacks de saturação e liberação ao ciclo de negociação M2M.

    on_saturation: pede ajuda a todos os vizinhos configurados.
    on_release:    agenda devolução de todos os workers emprestados e notifica origens.
    """
    def _on_saturation(needed: int) -> None:
        loop = asyncio.get_event_loop()
        for nid in list(m.neighbors):
            loop.create_task(m.request_help_to(nid, needed))

    def _on_release() -> None:
        loop = asyncio.get_event_loop()
        for wid, info in list(m.borrowed_in.items()):
            orig = info.get("origem")
            m.pending_releases[wid] = orig
            logger.info("Liberação agendada: Worker %s (origem %s)", wid, orig)
            if orig:
                loop.create_task(m._notify_origin_returned(wid, orig))

    m.on_saturation = _on_saturation
    m.on_release    = _on_release


async def run_server(host: str = DEFAULT_HOST,
                     port: int = DEFAULT_TCP_PORT,
                     master_id: str = DEFAULT_MASTER_ID,
                     tasks: Optional[Iterable[str]] = None,
                     name: Optional[str] = None,
                     advertise_ip: Optional[str] = None,
                     disc_port: Optional[int] = None,
                     neighbors: Optional[dict] = None,
                     capacity: int = DEFAULT_CAPACITY,
                     release_threshold: int = DEFAULT_RELEASE_THRESHOLD,
                     max_task_attempts: int = DEFAULT_MAX_TASK_ATTEMPTS) -> None:
    """Cria e inicia o Master. Se disc_port for dado, sobe também o responder UDP."""
    m = Master(host, port, master_id, tasks=tasks, name=name,
               advertise_ip=advertise_ip, capacity=capacity,
               release_threshold=release_threshold,
               max_task_attempts=max_task_attempts)
    if neighbors:
        m.neighbors.update(neighbors)
    _setup_auto_callbacks(m)
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


# ────────────────────────────────────────────────────────────────
# Ponto de entrada — main()
# ────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Master — Sprint 01 (Heartbeat) + 02 (Tarefas) + 03 (Negociação M2M)")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"IP de escuta TCP (padrão: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_TCP_PORT,
                        help=f"Porta TCP (padrão: {DEFAULT_TCP_PORT})")
    parser.add_argument("--id", default=DEFAULT_MASTER_ID,
                        help=f"master_id / SERVER_UUID (padrão: {DEFAULT_MASTER_ID})")
    parser.add_argument("--name", default=None,
                        help="MASTER_NAME para descoberta/eleição (ex.: MASTER_1)")
    parser.add_argument("--advertise-ip", default=None,
                        help="IP anunciado nas DISCOVERY_REPLY (auto-detecta se omitido)")
    parser.add_argument("--disc-port", type=int, default=DEFAULT_DISC_PORT,
                        help=f"Porta UDP de descoberta (0 = desativada; padrão: {DEFAULT_DISC_PORT})")
    parser.add_argument("--tasks", default=DEFAULT_TASKS,
                        help=f"Lista inicial de tarefas separada por vírgula (padrão: {DEFAULT_TASKS})")
    parser.add_argument("--neighbors", default=DEFAULT_NEIGHBORS,
                        help="Vizinhos M2M: 'B@127.0.0.1:8001,C@127.0.0.1:8002'")
    parser.add_argument("--capacity", type=int, default=DEFAULT_CAPACITY,
                        help=f"Threshold de saturação Sprint 3 (padrão: {DEFAULT_CAPACITY})")
    parser.add_argument("--release-threshold", type=int, default=DEFAULT_RELEASE_THRESHOLD,
                        help=f"Threshold de liberação Sprint 3 (padrão: {DEFAULT_RELEASE_THRESHOLD})")
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_TASK_ATTEMPTS,
                        help=f"Tentativas por tarefa antes de descartar em NOK (padrão: {DEFAULT_MAX_TASK_ATTEMPTS})")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    tarefas = [t.strip() for t in args.tasks.split(",") if t.strip()]
    disc = args.disc_port if args.disc_port and args.disc_port > 0 else None
    vizinhos = _parse_neighbors(args.neighbors)

    try:
        asyncio.run(run_server(
            host=args.host,
            port=args.port,
            master_id=args.id,
            tasks=tarefas,
            name=args.name,
            advertise_ip=args.advertise_ip,
            disc_port=disc,
            neighbors=vizinhos,
            capacity=args.capacity,
            release_threshold=args.release_threshold,
            max_task_attempts=args.max_attempts,
        ))
    except KeyboardInterrupt:
        logger.info("Master interrompido pelo usuário")


if __name__ == "__main__":
    main()
