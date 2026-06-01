# Sprint 2.1 — Descoberta Dinâmica e Eleição de Master — Implementation Plan

> **STATUS DE EXECUÇÃO (2026-05-31): ✅ EXECUTADO.** Pasta cumulativa
> `sprints/sprint02_1_discovery/` criada e implementada. Testes: **33/33
> passando** (18 das sprints 01/02 + 15 novos cobrindo CT01–CT05, e2e e
> bootstrap). Demo automática validada (descoberta→eleição→heartbeat e
> NO_MASTER_FOUND). Validação extra entre processos reais por **broadcast em
> loopback** funcionou ponta a ponta (DISCOVERY→ELECTION→CONNECTING→QUERY→ACK).
> Broadcast/multicast multi-máquina deve ser validado na LAN (receita no README).
> Commits a fazer localmente.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que o Worker descubra Masters por UDP (broadcast padrão), eleja um de forma determinística pelo nome, faça a transição para TCP com handshake de eleição (ELECTION_ACK→ACCEPTED) e então inicie o Heartbeat/tarefas já existentes.

**Architecture:** Pasta cumulativa `sprints/sprint02_1_discovery/` (Sprint 01 + 02 + descoberta). Transporte UDP via `asyncio.create_datagram_endpoint`, com lógica (eleição/parsing) separada do transporte para testabilidade. Master roda UDP responder + TCP server no mesmo event loop. Worker faz bootstrap (discover→elect→connect→confirm) antes do heartbeat.

**Tech Stack:** Python 3.8+, asyncio (DatagramProtocol + Streams), pytest (+ runner standalone `run_tests.py`).

---

### Task 0: Reorganização — nova pasta cumulativa da Sprint 2.1

**Files:**
- Create dir: `sprints/sprint02_1_discovery/` (cópia da `sprint02_tarefas`)

- [ ] **Step 1: Criar a base cumulativa (cópia da Sprint 02)**

```bash
cp -r sprints/sprint02_tarefas sprints/sprint02_1_discovery
```

- [ ] **Step 2: Verificar que a base (Sprint 01+02) roda intacta**

```bash
cd sprints/sprint02_1_discovery && python run_tests.py
# Esperado: 18/18 testes (heartbeat + tarefas) passam antes de adicionar a descoberta
```

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "chore(sprint-2.1): cria pasta cumulativa a partir da Sprint 02"
```

---

### Task 1: Lógica pura de eleição e parsing (TDD, sem rede)

**Files:**
- Create: `sprints/sprint02_1_discovery/src/heartbeat/discovery.py`
- Create: `sprints/sprint02_1_discovery/tests/test_discovery_logic.py`

- [ ] **Step 1: Escrever os testes falhando (CT02 eleição, CT05 parsing)**

```python
from src.heartbeat import discovery

def test_elege_menor_nome_lexicografico():
    replies = [
        {"MASTER_NAME": "MASTER_2", "MASTER_IP": "1.1.1.2", "MASTER_PORT": 10000},
        {"MASTER_NAME": "MASTER_1", "MASTER_IP": "1.1.1.1", "MASTER_PORT": 10000},
        {"MASTER_NAME": "MASTER_3", "MASTER_IP": "1.1.1.3", "MASTER_PORT": 10000},
    ]
    assert discovery.elect_master(replies)["MASTER_NAME"] == "MASTER_1"

def test_ordenacao_natural_master10_depois_de_master2():
    replies = [
        {"MASTER_NAME": "MASTER_10", "MASTER_IP": "1.1.1.10", "MASTER_PORT": 10000},
        {"MASTER_NAME": "MASTER_2", "MASTER_IP": "1.1.1.2", "MASTER_PORT": 10000},
    ]
    assert discovery.elect_master(replies)["MASTER_NAME"] == "MASTER_2"

def test_elect_vazio_retorna_none():
    assert discovery.elect_master([]) is None

def test_parse_reply_valida_ok():
    raw = {"TYPE": "DISCOVERY_REPLY", "MASTER_NAME": "MASTER_1",
           "MASTER_IP": "1.1.1.1", "MASTER_PORT": 10000, "STATUS": "AVAILABLE"}
    assert discovery.parse_reply(raw)["MASTER_NAME"] == "MASTER_1"

def test_parse_reply_sem_master_port_descarta():
    raw = {"TYPE": "DISCOVERY_REPLY", "MASTER_NAME": "MASTER_1", "MASTER_IP": "1.1.1.1"}
    assert discovery.parse_reply(raw) is None  # CT05

def test_parse_reply_ignora_campos_extras():
    raw = {"TYPE": "DISCOVERY_REPLY", "MASTER_NAME": "MASTER_1", "MASTER_IP": "1.1.1.1",
           "MASTER_PORT": 10000, "EXTRA": "x"}
    assert discovery.parse_reply(raw)["MASTER_PORT"] == 10000
```

- [ ] **Step 2: Implementar `discovery.py` (lógica)**

```python
"""discovery.py — Descoberta (UDP) e eleição determinística de Master.

A lógica (parse/eleição) é separada do transporte (datagram endpoint) para
permitir testes sem rede. Broadcast é o padrão; multicast é opcional.
"""
import asyncio, logging, re, socket
from src.heartbeat import messaging

logger = logging.getLogger("discovery")

DISC_PORT = 5000
MULTICAST_GROUP = "239.255.255.250"
BROADCAST_ADDR = "255.255.255.255"
COLLECT_WINDOW = 3.0
REQUIRED_REPLY = ("MASTER_NAME", "MASTER_IP", "MASTER_PORT")

def _natural_key(name):
    # "MASTER_10" -> ("master_", 10) para ordenar 2 < 10 corretamente
    m = re.match(r"^(.*?)(\d+)$", name or "")
    if m:
        return (m.group(1).lower(), int(m.group(2)))
    return ((name or "").lower(), -1)

def parse_reply(raw):
    if not isinstance(raw, dict) or raw.get("TYPE") != "DISCOVERY_REPLY":
        return None
    for campo in REQUIRED_REPLY:
        if campo not in raw:
            logger.warning("DISCOVERY_REPLY descartada (faltou %s): %s", campo, raw)
            return None
    return raw

def elect_master(replies):
    validos = [r for r in (parse_reply(x) for x in replies) if r]
    if not validos:
        return None
    eleito = min(validos, key=lambda r: _natural_key(r["MASTER_NAME"]))
    logger.info("ELECTION: eleito %s entre %d candidato(s)",
                eleito["MASTER_NAME"], len(validos))
    return eleito
```

- [ ] **Step 3: Rodar os testes (verde)**

```bash
cd sprints/sprint02_1_discovery && python -m pytest tests/test_discovery_logic.py -q
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat(sprint-2.1): lógica de eleição determinística e parsing de DISCOVERY_REPLY"
```

---

### Task 2: Transporte UDP — `discover()` e protocolo de datagrama

**Files:**
- Modify: `sprints/sprint02_1_discovery/src/heartbeat/discovery.py`
- Create: `sprints/sprint02_1_discovery/tests/test_discovery_udp.py`

- [ ] **Step 1: Teste de integração em loopback (CT01 lado descoberta)**

Sobe um responder UDP de teste em `127.0.0.1:<porta>` que responde `DISCOVERY_REPLY`;
o Worker chama `discover(..., target=("127.0.0.1", porta), window=0.5)` e deve
coletar 1 reply. (O parâmetro `target` permite unicast em loopback nos testes;
em produção o destino é broadcast/multicast.)

```python
import asyncio, contextlib
from src.heartbeat import discovery, messaging

class _FakeMaster(asyncio.DatagramProtocol):
    def __init__(self, reply): self.reply = reply
    def connection_made(self, transport): self.tr = transport
    def datagram_received(self, data, addr):
        self.tr.sendto(messaging.encode_message(self.reply), addr)

async def _sobe_fake(reply):
    loop = asyncio.get_running_loop()
    tr, pr = await loop.create_datagram_endpoint(
        lambda: _FakeMaster(reply), local_addr=("127.0.0.1", 0))
    return tr, tr.get_extra_info("sockname")[1]

def test_discover_coleta_uma_reply_loopback():
    reply = {"TYPE": "DISCOVERY_REPLY", "MASTER_NAME": "MASTER_1",
             "MASTER_IP": "127.0.0.1", "MASTER_PORT": 10000, "STATUS": "AVAILABLE"}
    async def cenario():
        tr, port = await _sobe_fake(reply)
        try:
            achados = await discovery.discover(
                "W-1", target=("127.0.0.1", port), window=0.5)
        finally:
            tr.close()
        return achados
    achados = asyncio.run(cenario())
    assert any(r["MASTER_NAME"] == "MASTER_1" for r in achados)

def test_discover_sem_resposta_retorna_vazio():  # CT03 (lado coleta)
    async def cenario():
        return await discovery.discover("W-1", target=("127.0.0.1", 59999),
                                        window=0.3)
    assert asyncio.run(cenario()) == []
```

- [ ] **Step 2: Implementar `DiscoveryProtocol` + `discover()`**

```python
class DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self):
        self.replies = []
    def datagram_received(self, data, addr):
        try:
            msg = messaging.decode_message(data)
        except Exception:
            logger.warning("Datagrama inválido de %s descartado", addr); return
        r = parse_reply(msg)
        if r:
            r.setdefault("_FROM", addr[0])
            self.replies.append(r)

async def discover(worker_uuid, *, disc_port=DISC_PORT, mode="broadcast",
                   group=MULTICAST_GROUP, window=COLLECT_WINDOW, target=None):
    """Envia DISCOVERY e coleta DISCOVERY_REPLY por `window` segundos.

    `target` (opcional) força um destino unicast — usado em teste (loopback).
    Em produção: mode="broadcast" -> 255.255.255.255; "multicast" -> group.
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
        await asyncio.sleep(window)            # janela fixa de coleta (3s)
        logger.info("DISCOVERY: coletadas %d resposta(s)", len(proto.replies))
        return list(proto.replies)
    finally:
        transport.close()
```

- [ ] **Step 3: Rodar testes**

```bash
cd sprints/sprint02_1_discovery && python -m pytest tests/test_discovery_udp.py -q
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat(sprint-2.1): transporte UDP de descoberta (broadcast padrão) com coleta por janela"
```

---

### Task 3: Master — responder UDP + ELECTION_ACK no TCP

**Files:**
- Modify: `sprints/sprint02_1_discovery/src/heartbeat/master_async.py`
- Test: `sprints/sprint02_1_discovery/tests/test_master_discovery.py`

- [ ] **Step 1: Teste — Master responde DISCOVERY via UDP (loopback) e ACCEPTED no TCP**

```python
import asyncio, contextlib
from src.heartbeat import master_async, messaging, discovery

def test_master_responde_discovery_reply():
    async def cenario():
        m = master_async.Master("127.0.0.1", 0, master_id="MASTER_1",
                                 name="MASTER_1", advertise_ip="127.0.0.1")
        await m.start_discovery(disc_port=0)        # sobe responder UDP em porta efêmera
        port = m.disc_transport.get_extra_info("sockname")[1]
        achados = await discovery.discover("W-1", target=("127.0.0.1", port), window=0.5)
        m.stop_discovery()
        return achados
    achados = asyncio.run(cenario())
    assert achados and achados[0]["MASTER_NAME"] == "MASTER_1"

def test_master_aceita_election_ack():
    async def cenario():
        m = master_async.Master("127.0.0.1", 0, master_id="MASTER_1", name="MASTER_1")
        server = await asyncio.start_server(m.handle_client, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await messaging.send_message(writer, {"TYPE": "ELECTION_ACK",
            "WORKER_UUID": "W-1", "SELECTED_MASTER": "MASTER_1"})
        resp = await asyncio.wait_for(messaging.read_message(reader), timeout=2)
        writer.close(); server.close()
        return resp
    resp = asyncio.run(cenario())
    assert resp["STATUS"] == "ACCEPTED" and resp["MASTER_NAME"] == "MASTER_1"
```

- [ ] **Step 2: Implementar no Master**

Adicionar ao `__init__`: `name`, `advertise_ip` (auto-detect se None), `disc_port`,
`disc_transport=None`. Função util `_detect_ip()` (socket UDP discado a 8.8.8.8,
sem enviar pacote). Classe `MasterDiscoveryProtocol` que responde `DISCOVERY_REPLY`
(com `MASTER_NAME`, `MASTER_IP`=advertise_ip, `MASTER_PORT`=self.port,
`STATUS`="AVAILABLE") via unicast ao `addr`. Métodos `start_discovery(disc_port)`
e `stop_discovery()`. No `handle_client`, novo ramo:

```python
elif msg.get("TYPE") == "ELECTION_ACK":
    sel = msg.get("SELECTED_MASTER")
    logger.info("ELECTION_ACK de %s (selecionado: %s)", msg.get("WORKER_UUID"), sel)
    await messaging.send_message(writer, {"TYPE": "ELECTION_ACK",
        "STATUS": "ACCEPTED", "MASTER_NAME": self.name})
```

Atualizar `start()` para subir também o responder UDP quando `disc_port` definido.

- [ ] **Step 3: Rodar testes**

```bash
cd sprints/sprint02_1_discovery && python -m pytest tests/test_master_discovery.py -q
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat(sprint-2.1): Master com responder UDP (DISCOVERY_REPLY) e ELECTION_ACK no TCP"
```

---

### Task 4: Worker — bootstrap (discover→elect→connect→confirm) + resiliência

**Files:**
- Modify: `sprints/sprint02_1_discovery/src/heartbeat/worker_async.py`
- Test: `sprints/sprint02_1_discovery/tests/test_worker_bootstrap.py`

- [ ] **Step 1: Testes — handshake de eleição e fallback NO_MASTER_FOUND**

```python
import asyncio, contextlib
from src.heartbeat import worker_async, master_async, messaging

def test_connect_and_confirm_ok():
    async def cenario():
        m = master_async.Master("127.0.0.1", 0, master_id="MASTER_1", name="MASTER_1")
        server = await asyncio.start_server(m.handle_client, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        master = {"MASTER_NAME": "MASTER_1", "MASTER_IP": "127.0.0.1", "MASTER_PORT": port}
        ok = await worker_async.connect_and_confirm(master, "W-1")
        server.close()
        return ok
    assert asyncio.run(cenario()) is not None  # retorna (host, port) em sucesso

def test_bootstrap_sem_master_aplica_fallback(monkeypatch=None):
    # discover devolve [] -> NO_MASTER_FOUND; limitamos a 2 tentativas
    async def fake_discover(*a, **k): return []
    async def cenario():
        worker_async.discovery.discover = fake_discover
        tentativas = await worker_async.bootstrap("W-1", max_attempts=2, base_backoff=0.01)
        return tentativas
    assert asyncio.run(cenario()) is None  # desiste após max_attempts (sem travar)
```

- [ ] **Step 2: Implementar `connect_and_confirm` e `bootstrap`**

```python
from src.heartbeat import discovery

async def connect_and_confirm(master, worker_uuid):
    host, port = master["MASTER_IP"], master["MASTER_PORT"]
    logger.info("CONNECTING: TCP %s:%s (master %s)", host, port, master["MASTER_NAME"])
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=RESPONSE_TIMEOUT)
        await messaging.send_message(writer, {"TYPE": "ELECTION_ACK",
            "WORKER_UUID": worker_uuid, "SELECTED_MASTER": master["MASTER_NAME"]})
        ack = await asyncio.wait_for(messaging.read_message(reader), timeout=RESPONSE_TIMEOUT)
        if ack and ack.get("STATUS") == "ACCEPTED":
            logger.info("Eleição confirmada por %s", ack.get("MASTER_NAME"))
            writer.close()
            with contextlib.suppress(Exception): await writer.wait_closed()
            return (host, port)
        logger.warning("ELECTION_ACK inesperado: %s", ack)
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as e:
        logger.warning("CONNECTING falhou (%s)", e)
    return None

async def bootstrap(worker_uuid, *, mode="broadcast", disc_port=discovery.DISC_PORT,
                    window=discovery.COLLECT_WINDOW, max_attempts=None, base_backoff=1.0):
    backoff = base_backoff; tentativa = 0
    while max_attempts is None or tentativa < max_attempts:
        tentativa += 1
        replies = await discovery.discover(worker_uuid, mode=mode,
                                           disc_port=disc_port, window=window)
        eleito = discovery.elect_master(replies)
        if eleito is None:
            logger.warning("NO_MASTER_FOUND (tentativa %d) — FALLBACK em %.1fs",
                           tentativa, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)
            continue
        alvo = await connect_and_confirm(eleito, worker_uuid)
        if alvo:
            return alvo
        logger.warning("FALLBACK: conexão pós-eleição falhou; invalida cache e refaz")
        backoff = base_backoff
    return None
```

Atualizar `main()`: remover `--host/--port` do Master; adicionar `--discovery-mode`
e `--disc-port`; após `bootstrap`, chamar `work_loop` no alvo retornado. Quando
`bootstrap` retorna `None` (só ocorre com `max_attempts`), encerra com log.

- [ ] **Step 3: Rodar testes**

```bash
cd sprints/sprint02_1_discovery && python -m pytest tests/test_worker_bootstrap.py -q
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat(sprint-2.1): Worker bootstrap (discover/elect/connect/confirm) com backoff e reeleição"
```

---

### Task 5: End-to-end e CT04 (queda pós-eleição)

**Files:**
- Test: `sprints/sprint02_1_discovery/tests/test_discovery_e2e.py`

- [ ] **Step 1: E2E — Master (UDP+TCP) sobe, Worker descobre→elege→conecta→confirma→1 heartbeat**

```python
def test_e2e_descoberta_ate_heartbeat():
    async def cenario():
        m = master_async.Master("127.0.0.1", 0, master_id="MASTER_1",
                                 name="MASTER_1", advertise_ip="127.0.0.1")
        server = await asyncio.start_server(m.handle_client, "127.0.0.1", 0)
        tcp_port = server.sockets[0].getsockname()[1]
        await m.start_discovery(disc_port=0, tcp_port=tcp_port)
        disc_port = m.disc_transport.get_extra_info("sockname")[1]
        # descobre via loopback, elege, confirma e faz 1 heartbeat
        replies = await discovery.discover("W-1", target=("127.0.0.1", disc_port), window=0.5)
        eleito = discovery.elect_master(replies)
        alvo = await worker_async.connect_and_confirm(eleito, "W-1")
        ok = await worker_async.run_once(alvo[0], alvo[1], "MASTER_1")
        m.stop_discovery(); server.close()
        return eleito["MASTER_NAME"], alvo is not None, ok
    nome, conectou, hb = asyncio.run(cenario())
    assert nome == "MASTER_1" and conectou and hb is True
```

(Para o e2e, `start_discovery` aceita `tcp_port` para anunciar a porta TCP real
do servidor efêmero na `DISCOVERY_REPLY`.)

- [ ] **Step 2: CT04 — queda pós-eleição dispara caminho de reinício**

Teste: após `connect_and_confirm`, fechar o server; `run_once` no alvo retorna
`False` (conexão recusada) — comprovando que o Worker detecta a queda (o
`bootstrap` real então re-descobriria; aqui validamos a detecção sem loop).

- [ ] **Step 3: Rodar a suíte inteira**

```bash
cd sprints/sprint02_1_discovery && python run_tests.py   # Sprint 01 + 02 + 2.1
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "test(sprint-2.1): e2e descoberta→heartbeat e CT04 (queda pós-eleição)"
```

---

### Task 6: Entrypoints, runner, demo e README (com receita LAN 2 máquinas)

**Files:**
- Modify: `master.py`, `worker.py`, `run_tests.py`
- Create: `scripts/run_discovery_demo.py`
- Create: `README.md` (Sprint 2.1)

- [ ] **Step 1: Entrypoints**
  - `master.py`: `--name MASTER_1`, `--port 10000` (TCP), `--disc-port 5000`,
    `--advertise-ip`, `--discovery-mode`. Sobe TCP + responder UDP.
  - `worker.py`: remove alvo fixo; `--uuid`, `--discovery-mode`, `--disc-port`.
    Faz `bootstrap` e segue para `work_loop`.

- [ ] **Step 2: `run_tests.py`** — incluir `tests.test_discovery_logic`,
  `tests.test_discovery_udp`, `tests.test_master_discovery`,
  `tests.test_worker_bootstrap`, `tests.test_discovery_e2e`.

- [ ] **Step 3: `scripts/run_discovery_demo.py`** — em um processo: sobe Master
  (UDP+TCP) com nome MASTER_1, roda a descoberta em loopback, elege, confirma e
  mostra o primeiro heartbeat. Demonstra também NO_MASTER_FOUND com porta sem
  responder.

- [ ] **Step 4: `README.md`** — payloads, fluxo, como rodar e **receita LAN com
  2 máquinas**:
  ```
  # Máquina A (Master):
  python master.py --name MASTER_1 --port 10000 --disc-port 5000
  # (rode outro Master em MASTER_2 em outra máquina, se quiser testar CT02)
  # Máquina B (Worker), mesma sub-rede:
  python worker.py --uuid W-101 --discovery-mode broadcast --disc-port 5000
  ```
  Incluir checklist do DoD (1–6) e nota sobre broadcast vs multicast.

- [ ] **Step 5: Verificação final**

```bash
cd sprints/sprint02_1_discovery && python run_tests.py
python scripts/run_discovery_demo.py
```

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "docs(sprint-2.1): entrypoints (sem IP fixo), demo, README com receita LAN e runner"
```

---

## Self-review

- **Cobertura da spec:** descoberta UDP (Tarefa 01), eleição determinística
  (Tarefa 02), transição TCP + handshake ELECTION_ACK/ACCEPTED (Tarefa 03),
  resiliência/backoff/reeleição + logs DISCOVERY/ELECTION/CONNECTING/FALLBACK
  (Tarefa 04). CT01–CT05 cobertos por testes (CT01 e3e; CT02 unidade; CT03
  coleta vazia + fallback; CT04 queda pós-eleição; CT05 parsing).
- **Sem placeholders:** cada passo traz arquivo, código e comando.
- **Reaproveitamento:** `messaging`, heartbeat e tarefas das sprints anteriores
  ficam intactos; a descoberta só adiciona e conecta o Worker ao fluxo existente.
- **Limitação honesta:** broadcast/multicast multi-máquina não é testável no
  sandbox (sem rede); validado em loopback + receita LAN no README.
- **Pontos abertos:** default broadcast (multicast via flag); `STATUS:"AVAILABLE"`
  informativo na reply.

## Execução

Após sua revisão, posso executar este plano aqui (implementar + rodar os testes)
e te entregar a pasta `sprints/sprint02_1_discovery/` pronta, com o resumo dos
testes, a receita de teste em LAN e os comandos de commit. Diga `executar`.
