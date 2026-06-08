# Sprint 3 — Protocolo de Negociação Master-to-Master — Implementation Plan

> **STATUS DE EXECUÇÃO (2026-05-31): ✅ EXECUTADO.** Pasta cumulativa
> `sprints/sprint03_negociacao/` criada e implementada. Testes: **54/54
> passando** (33 das sprints 01/02/2.1 + 21 novos cobrindo CT01–CT09, e2e e
> unidade do envelope M2M). Demo automática validada (saturação→pedido→aceite→
> empréstimo→tarefa→normalização→devolução). Correção relevante durante a
> execução: o `request_help_to` passou a fechar a conexão M2M ao final, evitando
> vazamento (atende ao DoD 9). Commits a fazer localmente.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar a negociação P2P entre Masters: um Master saturado pede ajuda a um vizinho, recebe Workers emprestados via redirecionamento, opera com eles pelo ciclo da Sprint 02 e os devolve quando a carga normaliza.

**Architecture:** Pasta cumulativa `sprints/sprint03_negociacao/` (Sprint 01 + 02 + 2.1 + negociação). AsyncIO (Master é servidor e cliente simultâneo no mesmo loop). Envelope M2M `{type, request_id, payload}`. Correlação por `request_id` (Future + timeout 5s). Carga programática (`set_load`) com histerese (capacity=100, release=60).

**Tech Stack:** Python 3.8+, asyncio, uuid (stdlib), pytest (+ runner standalone `run_tests.py`).

---

### Task 0: Nova pasta cumulativa da Sprint 3

**Files:**
- Create dir: `sprints/sprint03_negociacao/` (cópia da `sprint02_1_discovery`)

- [ ] **Step 1: Criar a base cumulativa**

```bash
cp -r sprints/sprint02_1_discovery sprints/sprint03_negociacao
```

- [ ] **Step 2: Verificar que a base (01+02+2.1) roda intacta**

```bash
cd sprints/sprint03_negociacao && python run_tests.py
# Esperado: 33/33 testes das sprints anteriores passam
```

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "chore(sprint-3): cria pasta cumulativa a partir da Sprint 2.1"
```

---

### Task 1: Envelope M2M e construtores (`m2m.py`) — TDD

**Files:**
- Create: `sprints/sprint03_negociacao/src/heartbeat/m2m.py`
- Create: `sprints/sprint03_negociacao/tests/test_m2m.py`

- [ ] **Step 1: Testes falhando**

```python
import uuid
from src.heartbeat import m2m

def test_request_id_e_uuid_v4():
    rid = m2m.new_request_id()
    assert uuid.UUID(rid).version == 4

def test_make_message_envelope():
    msg = m2m.make_message("request_help", {"x": 1}, request_id="r1")
    assert msg == {"type": "request_help", "request_id": "r1", "payload": {"x": 1}}

def test_make_message_gera_request_id_quando_ausente():
    msg = m2m.make_message("ping", {})
    assert uuid.UUID(msg["request_id"]).version == 4

def test_request_help_payload():
    msg = m2m.request_help("A", current_load=150, capacity=100, workers_needed=2)
    assert msg["type"] == "request_help"
    assert msg["payload"] == {"master_id": "A", "current_load": 150,
                               "capacity": 100, "workers_needed": 2}

def test_response_accepted_mantem_request_id():
    msg = m2m.response_accepted([{"id": "B1", "address": "ip:1"}], request_id="r9")
    assert msg["request_id"] == "r9"
    assert msg["payload"]["workers_offered"] == 1
    assert msg["payload"]["worker_details"][0]["id"] == "B1"

def test_response_rejected_reason_valido():
    msg = m2m.response_rejected("high_load", request_id="r9")
    assert msg["payload"]["reason"] == "high_load"

def test_command_redirect_e_register_e_release_e_notify():
    assert m2m.command_redirect("ip_a:8000")["type"] == "command_redirect"
    assert m2m.register_temporary_worker("B1", "ip_b:8000")["type"] == "register_temporary_worker"
    assert m2m.command_release("ip_b:8000")["type"] == "command_release"
    assert m2m.notify_worker_returned("B1")["type"] == "notify_worker_returned"
```

- [ ] **Step 2: Implementar `m2m.py`**

```python
"""m2m.py — Envelope e construtores das mensagens Master-to-Master (Sprint 3)."""
import uuid

REASONS = {"high_load", "no_workers_available", "refused"}

def new_request_id() -> str:
    return str(uuid.uuid4())

def make_message(type_, payload, request_id=None):
    return {"type": type_, "request_id": request_id or new_request_id(),
            "payload": payload or {}}

def request_help(master_id, current_load, capacity, workers_needed, request_id=None):
    return make_message("request_help", {
        "master_id": master_id, "current_load": current_load,
        "capacity": capacity, "workers_needed": workers_needed}, request_id)

def response_accepted(worker_details, request_id=None):
    return make_message("response_accepted", {
        "workers_offered": len(worker_details),
        "worker_details": worker_details}, request_id)

def response_rejected(reason, request_id=None):
    return make_message("response_rejected", {"reason": reason}, request_id)

def command_redirect(new_master_address, request_id=None):
    return make_message("command_redirect",
                        {"new_master_address": new_master_address}, request_id)

def register_temporary_worker(worker_id, original_master_address, request_id=None):
    return make_message("register_temporary_worker", {
        "worker_id": worker_id,
        "original_master_address": original_master_address}, request_id)

def command_release(original_master_address, request_id=None):
    return make_message("command_release",
                        {"original_master_address": original_master_address}, request_id)

def notify_worker_returned(worker_id, request_id=None):
    return make_message("notify_worker_returned", {"worker_id": worker_id}, request_id)
```

- [ ] **Step 3: Rodar testes**

```bash
cd sprints/sprint03_negociacao && python -m pytest tests/test_m2m.py -q
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat(sprint-3): envelope M2M e construtores dos 7 tipos de mensagem"
```

---

### Task 2: Estado de carga + detecção de saturação (histerese)

**Files:**
- Modify: `sprints/sprint03_negociacao/src/heartbeat/master_async.py`
- Test: `sprints/sprint03_negociacao/tests/test_load_state.py`

- [ ] **Step 1: Testes**

```python
from src.heartbeat import master_async

def test_set_load_detecta_saturacao():
    m = master_async.Master("127.0.0.1", 0, capacity=100, release_threshold=60)
    eventos = []
    m.on_saturation = lambda needed: eventos.append(("sat", needed))
    m.on_release = lambda: eventos.append(("rel",))
    m.set_load(150)              # > capacity -> saturação
    assert eventos and eventos[0][0] == "sat"

def test_set_load_detecta_liberacao_com_histerese():
    m = master_async.Master("127.0.0.1", 0, capacity=100, release_threshold=60)
    estados = []
    m.on_saturation = lambda needed: estados.append("sat")
    m.on_release = lambda: estados.append("rel")
    m.set_load(150)              # satura
    m.set_load(80)               # entre 60 e 100: NÃO libera (histerese)
    assert "rel" not in estados
    m.set_load(50)               # < release_threshold: libera
    assert "rel" in estados

def test_workers_needed_proporcional_ao_excedente():
    m = master_async.Master("127.0.0.1", 0, capacity=100, release_threshold=60)
    assert m.compute_workers_needed(150) >= 1
```

- [ ] **Step 2: Implementar no `__init__` do Master**

Adicionar parâmetros `capacity=100`, `release_threshold=60`; atributos
`current_load=0`, `_saturated=False`; hooks `on_saturation`/`on_release`
(callables, default `None`); métodos:

```python
def set_load(self, n: int) -> None:
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
    return max(1, excedente // max(1, self.capacity // 2))  # proporcional
```

- [ ] **Step 3: Rodar testes** • **Step 4: Commit**

```bash
cd sprints/sprint03_negociacao && python -m pytest tests/test_load_state.py -q
git add -A && git commit -m "feat(sprint-3): estado de carga e detecção de saturação com histerese"
```

---

### Task 3: Negociação — request_help / response (correlação + timeout)

**Files:**
- Modify: `sprints/sprint03_negociacao/src/heartbeat/master_async.py`
- Test: `sprints/sprint03_negociacao/tests/test_negociacao.py`

- [ ] **Step 1: Testes (CT01, CT02, CT03, CT07)**

Sobe 2 Masters reais em loopback. A pede ajuda a B:
- CT01: B com 2 ociosos → `response_accepted`, `workers_offered==2`, mesmo `request_id`.
- CT02: B saturado → `response_rejected`, `reason=="high_load"`.
- CT03: A dispara 2 pedidos concorrentes (para B e C) → cada resposta com o
  `request_id` correto.
- CT07: B "mudo" (não responde) → `request_help_to` retorna `None` após ~5s
  (usar `timeout=0.5` no teste para rapidez) e libera o `request_id`.

```python
import asyncio, contextlib
from src.heartbeat import master_async, m2m, messaging

async def _sobe_master(name, ociosos=0, carga_alta=False):
    m = master_async.Master("127.0.0.1", 0, master_id=name, name=name)
    m.idle_workers = [{"id": f"{name}{i}", "address": f"ip:{i}"} for i in range(ociosos)]
    if carga_alta:
        m.current_load = 999; m._saturated = True
    server = await asyncio.start_server(m.handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return m, server, port

def test_ct01_help_aceito():
    async def cenario():
        b, sb, pb = await _sobe_master("B", ociosos=2)
        a, sa, pa = await _sobe_master("A")
        a.neighbors["B"] = ("127.0.0.1", pb)
        resp = await a.request_help_to("B", workers_needed=2, timeout=2.0)
        sb.close(); sa.close()
        return resp
    resp = asyncio.run(cenario())
    assert resp["type"] == "response_accepted"
    assert resp["payload"]["workers_offered"] == 2

def test_ct02_help_recusado():
    async def cenario():
        b, sb, pb = await _sobe_master("B", ociosos=0, carga_alta=True)
        a, sa, pa = await _sobe_master("A")
        a.neighbors["B"] = ("127.0.0.1", pb)
        resp = await a.request_help_to("B", workers_needed=2, timeout=2.0)
        sb.close(); sa.close()
        return resp
    resp = asyncio.run(cenario())
    assert resp["type"] == "response_rejected"
    assert resp["payload"]["reason"] in ("high_load", "no_workers_available")

def test_ct07_timeout():
    async def cenario():
        # vizinho inexistente -> conexão falha rápido OU sem resposta
        a, sa, pa = await _sobe_master("A")
        a.neighbors["B"] = ("127.0.0.1", 59998)
        resp = await a.request_help_to("B", workers_needed=1, timeout=0.5)
        sa.close()
        return resp
    assert asyncio.run(cenario()) is None
```

- [ ] **Step 2: Implementar negociação no Master**

Atributos: `neighbors={}`, `idle_workers=[]`, `pending={}`, `m2m_conns={}`.
No dispatch (`handle_client`), tratar:
- `request_help` → `evaluate_help_request(payload)`: se `_saturated` ou sem
  ociosos suficientes → `response_rejected` (`high_load`/`no_workers_available`);
  senão separa N de `idle_workers` → `response_accepted` (mesmo `request_id`) e
  agenda `redirect_workers`.
- `response_accepted`/`response_rejected` → resolve `pending[request_id]`.
- `notify_worker_returned`, `register_temporary_worker` → Tasks 4/5.
- `type` desconhecido → loga e ignora (CT09).

```python
async def request_help_to(self, neighbor_id, workers_needed, timeout=5.0):
    ip, port = self.neighbors[neighbor_id]
    msg = m2m.request_help(self.master_id, self.current_load, self.capacity, workers_needed)
    rid = msg["request_id"]
    fut = asyncio.get_running_loop().create_future()
    self.pending[rid] = fut
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
    # lê respostas nessa conexão até casar o request_id (ou timeout)
    async def _ler():
        while True:
            resp = await messaging.read_message(reader)
            if resp is None:
                return None
            if resp.get("request_id") == rid and not fut.done():
                fut.set_result(resp); return None
    leitor = asyncio.create_task(_ler())
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("TIMEOUT (%.1fs) aguardando resposta de %s; libera rid=%s",
                       timeout, neighbor_id, rid)
        return None
    finally:
        self.pending.pop(rid, None)
        leitor.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await leitor
```

`evaluate_help_request` retorna o dict de resposta (accepted/rejected) com o
mesmo `request_id` recebido.

- [ ] **Step 3: Rodar testes** • **Step 4: Commit**

```bash
cd sprints/sprint03_negociacao && python -m pytest tests/test_negociacao.py -q
git add -A && git commit -m "feat(sprint-3): request_help/response com correlação por request_id e timeout 5s"
```

---

### Task 4: Redirecionamento e registro do Worker emprestado

**Files:**
- Modify: `master_async.py`, `worker_async.py`
- Test: `sprints/sprint03_negociacao/tests/test_redirect_register.py`

- [ ] **Step 1: Testes (CT04, CT05)**

- CT04: Worker recebe `command_redirect` (simulado), conecta ao Master A e envia
  `register_temporary_worker` → A registra em `borrowed_in` e, na apresentação
  seguinte, o Worker manda `ALIVE` com `SERVER_UUID` = Master B.
- CT05: A tem tarefa na fila; o emprestado pede trabalho → QUERY → STATUS OK →
  ACK; log marca execução por emprestado.

- [ ] **Step 2: Implementar**

Master: handler `register_temporary_worker` → `self.borrowed_in[worker_id] =
{"origem": original_master_address}`; contador no log. (O ciclo de tarefas com
`SERVER_UUID` já existe da Sprint 02.)

Worker: `handle_command_redirect(msg)` → encerra ciclo atual graciosamente,
extrai `new_master_address`, conecta e envia `register_temporary_worker` (via
`m2m`), depois entra no `work_loop` com `origin_master` = Master de origem
(preenche `SERVER_UUID`). Parser de endereço `"ip:port"`.

- [ ] **Step 3: Rodar testes** • **Step 4: Commit**

```bash
cd sprints/sprint03_negociacao && python -m pytest tests/test_redirect_register.py -q
git add -A && git commit -m "feat(sprint-3): command_redirect no Worker e register_temporary_worker no Master"
```

---

### Task 5: Devolução (command_release + notify_worker_returned)

**Files:**
- Modify: `master_async.py`, `worker_async.py`
- Test: `sprints/sprint03_negociacao/tests/test_devolucao.py`

- [ ] **Step 1: Testes (CT06)**

Worker registrado como emprestado em A; `set_load` cai abaixo de 60 → A emite
`command_release` ao Worker e `notify_worker_returned` a B (na conexão M2M) →
Worker reconecta a B (apresentação Sprint 02). Verificar que A remove o worker de
`borrowed_in` e B é notificado.

- [ ] **Step 2: Implementar**

Master A: `release_worker(worker_id)` → envia `command_release` ao Worker e
`notify_worker_returned` ao Master de origem; remove de `borrowed_in`.
`on_release` (hook do Task 2) chama `release_worker` para cada emprestado.
Master B: handler `notify_worker_returned` → readiciona o worker à `idle_workers`/
farm e loga.
Worker: `handle_command_release(msg)` → reconecta ao `original_master_address`.

- [ ] **Step 3: Rodar testes** • **Step 4: Commit**

```bash
cd sprints/sprint03_negociacao && python -m pytest tests/test_devolucao.py -q
git add -A && git commit -m "feat(sprint-3): devolução do worker (command_release + notify_worker_returned)"
```

---

### Task 6: Resiliência — type desconhecido, queda do receptor (CT08, CT09)

**Files:**
- Modify: `master_async.py`, `worker_async.py`
- Test: `sprints/sprint03_negociacao/tests/test_resiliencia_m2m.py`

- [ ] **Step 1: Testes**

- CT09: enviar mensagem M2M com `type` inexistente → Master loga e ignora,
  conexão segue viva (envia um `request_help` válido depois e recebe resposta).
- CT08: Worker emprestado conectado a A; A cai → no próximo ciclo o Worker
  detecta a queda (run_once/erro) e tenta reconectar ao Master de origem
  (verificar tentativa de reconexão a B).

- [ ] **Step 2: Implementar/garantir**

Dispatch já ignora `type`/mensagem desconhecida com log (reaproveita o `else`).
No Worker emprestado, em falha de conexão com A, acionar o caminho de retorno a
B (origem) antes do fallback geral.

- [ ] **Step 3: Rodar testes** • **Step 4: Commit**

```bash
cd sprints/sprint03_negociacao && python -m pytest tests/test_resiliencia_m2m.py -q
git add -A && git commit -m "test(sprint-3): resiliência M2M (type desconhecido, queda do receptor)"
```

---

### Task 7: E2E, entrypoints, runner, demo e README

**Files:**
- Modify: `master.py`, `worker.py`, `run_tests.py`
- Create: `scripts/run_negociacao_demo.py`
- Create/overwrite: `README.md`

- [ ] **Step 1: E2E** — teste que encadeia o ciclo completo do diagrama:
  A satura → pede a B → accepted → redirect → worker registra em A (SERVER_UUID) →
  A entrega QUERY → OK → ACK → A normaliza → release + notify → worker volta a B.

- [ ] **Step 2: Entrypoints**
  - `master.py`: `--neighbors B@127.0.0.1:8001,C@127.0.0.1:8002`, `--capacity`,
    `--release-threshold`, e um `--simulate-load` opcional (lista de cargas no
    tempo) para a demo.
  - `worker.py`: tratar `command_redirect`/`command_release` no loop.

- [ ] **Step 3: `run_tests.py`** — incluir `test_m2m`, `test_load_state`,
  `test_negociacao`, `test_redirect_register`, `test_devolucao`,
  `test_resiliencia_m2m`, `test_m2m_e2e`.

- [ ] **Step 4: `scripts/run_negociacao_demo.py`** — em um processo: sobe Master B
  (com 2 ociosos) e Master A; A satura via `set_load`, negocia com B, "empresta"
  os workers (simulado em loopback), mostra o ciclo de tarefas e depois a
  devolução ao normalizar a carga.

- [ ] **Step 5: README.md** — os 7 tipos, o diagrama de fluxo, como rodar 2
  Masters + Worker, thresholds/histerese e checklist do DoD (2–9) com CT01–CT09.

- [ ] **Step 6: Verificação final + commit**

```bash
cd sprints/sprint03_negociacao && python run_tests.py
python scripts/run_negociacao_demo.py
git add -A && git commit -m "docs(sprint-3): e2e, entrypoints M2M, demo, README e runner"
```

---

## Self-review

- **Cobertura da spec:** conexão M2M (Tarefa 01), saturação/histerese (Tarefa 02),
  negociação request_help/response com correlação e timeout (Tarefa 03),
  redirecionamento + registro (Tarefa 04), devolução (Tarefa 05), resiliência
  (Tarefa 06), logs/observabilidade ao longo (Tarefa 07). CT01–CT09 cobertos.
- **Sem placeholders:** cada passo tem arquivo, código/descrição e comando.
- **Reaproveitamento:** `messaging`, heartbeat, tarefas (com `SERVER_UUID`) e
  descoberta ficam intactos; a negociação só adiciona.
- **Concorrência:** asyncio single-thread garante atomicidade entre `await`s
  (Nota 38) sem locks.
- **Limitação honesta:** interoperabilidade entre equipes (DoD 7) e rede real não
  são testáveis no sandbox; garantidas pela aderência estrita aos payloads e
  validáveis em LAN.
- **Pontos abertos:** thresholds default (100/60), diretório de vizinhos estático.

## Execução

Após sua revisão, posso executar este plano aqui (implementar + rodar os testes)
e entregar a pasta `sprints/sprint03_negociacao/` pronta, com o resumo dos testes
e os comandos de commit. Diga `executar`.
