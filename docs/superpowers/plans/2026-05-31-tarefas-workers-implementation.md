# Sprint 2 — Comunicação de Tarefas e Apresentação de Workers — Implementation Plan

> **STATUS DE EXECUÇÃO (2026-05-31): ✅ EXECUTADO.** Reorganização em pastas de
> sprint feita; código implementado em `sprints/sprint02_tarefas/`. Testes:
> **18/18 passando** (7 da Sprint 01 + 11 novos cobrindo CT01–CT05 e o ciclo
> completo). Demo end-to-end validada (QUERY→OK/NOK→ACK e NO_TASK), incluindo
> worker emprestado. Ambiente sem rede/git: testes verificados via `run_tests.py`
> (na sua máquina use `pytest -q`); commits a fazer localmente.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar o ciclo de vida completo de uma tarefa (apresentação do Worker → distribuição de tarefa → processamento → reporte de status → ACK), reaproveitando a base da Sprint 01.

**Architecture:** Organização por pastas de sprint. `sprints/sprint02_tarefas/` é cumulativa (Sprint 01 + Sprint 02) e auto-contida. Master assíncrono com fila de tarefas (`deque`) e registro de workers (`dict`), sem locks (event loop single-thread). Worker com loop de trabalho e reconexão. Reaproveita `messaging.py`.

**Tech Stack:** Python 3.8+, asyncio, pytest (+ runner standalone `run_tests.py`).

---

### Task 0: Reorganização em pastas de sprint

**Files:**
- Create dir: `sprints/sprint01_heartbeat/` (retrato da Sprint 01)
- Create dir: `sprints/sprint02_tarefas/` (cópia da 01 = base cumulativa da 02)

- [ ] **Step 1: Mover a Sprint 01 para sua pasta**

```bash
mkdir -p sprints/sprint01_heartbeat
git mv src tests scripts master.py worker.py run_tests.py requirements.txt README_SPRINT01.md sprints/sprint01_heartbeat/ 2>/dev/null \
  || (mkdir -p sprints/sprint01_heartbeat && cp -r src tests scripts master.py worker.py run_tests.py requirements.txt README_SPRINT01.md sprints/sprint01_heartbeat/)
```

- [ ] **Step 2: Criar a base cumulativa da Sprint 02 (cópia da 01)**

```bash
cp -r sprints/sprint01_heartbeat sprints/sprint02_tarefas
```

- [ ] **Step 3: Verificar que a Sprint 02 roda como está (herdando a 01)**

```bash
cd sprints/sprint02_tarefas && python run_tests.py
# Esperado: os 7 testes da Sprint 01 passam (base intacta antes de adicionar a 02)
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "chore(sprint-02): organiza projeto em pastas por sprint (base cumulativa)"
```

---

### Task 1: Novos payloads no messaging (testes)

`messaging.py` é genérico e não muda; apenas garantimos cobertura dos novos payloads.

**Files:**
- Test: `sprints/sprint02_tarefas/tests/test_messaging_sprint02.py`

- [ ] **Step 1: Escrever os testes**

```python
from src.heartbeat import messaging

def test_roundtrip_apresentacao_local():
    obj = {"WORKER": "ALIVE", "WORKER_UUID": "W-123"}
    assert messaging.decode_message(messaging.encode_message(obj)) == obj

def test_roundtrip_apresentacao_emprestado():
    obj = {"WORKER": "ALIVE", "WORKER_UUID": "W-999", "SERVER_UUID": "Master-B"}
    assert messaging.decode_message(messaging.encode_message(obj)) == obj

def test_roundtrip_query_e_status():
    for obj in (
        {"TASK": "QUERY", "USER": "Michel"},
        {"TASK": "NO_TASK"},
        {"STATUS": "OK", "TASK": "QUERY", "WORKER_UUID": "W-123"},
        {"STATUS": "ACK", "WORKER_UUID": "W-123"},
    ):
        assert messaging.decode_message(messaging.encode_message(obj)) == obj
```

- [ ] **Step 2: Rodar e verificar que passam** (`messaging` já existe)

```bash
cd sprints/sprint02_tarefas && python -m pytest tests/test_messaging_sprint02.py -q
```

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "test(sprint-02): cobre roundtrip dos payloads de tarefas"
```

---

### Task 2: Master — fila de tarefas + apresentação (WORKER:ALIVE → QUERY/NO_TASK)

**Files:**
- Modify: `sprints/sprint02_tarefas/src/heartbeat/master_async.py`
- Test: `sprints/sprint02_tarefas/tests/test_tarefas_integration.py`

- [ ] **Step 1: Escrever o teste de integração falhando (CT01, CT02, CT03)**

```python
import asyncio, contextlib
from src.heartbeat import master_async
from src.heartbeat import messaging

async def _abre(port, tasks):
    m = master_async.Master("127.0.0.1", port, master_id="Master_A", tasks=tasks)
    server = asyncio.create_task(m.start())
    await asyncio.sleep(0.15)
    return m, server

async def _presenta(port, payload):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    await messaging.send_message(writer, payload)
    resp = await asyncio.wait_for(messaging.read_message(reader), timeout=2)
    writer.close()
    await writer.wait_closed()
    return resp

def test_ct01_worker_local_recebe_query():
    async def cenario():
        m, server = await _abre(9201, ["Michel"])
        resp = await _presenta(9201, {"WORKER": "ALIVE", "WORKER_UUID": "W-123"})
        server.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server
        return resp
    resp = asyncio.run(cenario())
    assert resp["TASK"] == "QUERY" and resp["USER"] == "Michel"

def test_ct03_fila_vazia_recebe_no_task():
    async def cenario():
        m, server = await _abre(9203, [])
        resp = await _presenta(9203, {"WORKER": "ALIVE", "WORKER_UUID": "W-123"})
        server.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server
        return resp
    resp = asyncio.run(cenario())
    assert resp == {"TASK": "NO_TASK"}
```

- [ ] **Step 2: Implementar fila + apresentação no Master**

Modificar `Master.__init__` para aceitar `tasks` e criar registro:

```python
from collections import deque

def __init__(self, host, port, master_id="Master_A", tasks=None):
    self.host = host
    self.port = port
    self.master_id = master_id
    self.tasks = deque(tasks or [])
    self.workers = {}        # uuid -> {"emprestado": bool, "origem": str|None, "concluidas": int}
    self._server = None
```

No `handle_client`, após obter `msg`, ramificar por tipo (mantendo o HEARTBEAT):

```python
if msg.get("TASK") == "HEARTBEAT" or msg.get("TASK") == "HEARTBEAT":
    ...  # bloco existente da Sprint 01 (responde ALIVE)
elif msg.get("WORKER") == "ALIVE":
    await self._handle_apresentacao(msg, writer, addr)
elif "STATUS" in msg:
    await self._handle_status(msg, writer, addr)   # Task 3
else:
    logger.warning("Mensagem não reconhecida ignorada: %s", msg)
```

Método de apresentação:

```python
async def _handle_apresentacao(self, msg, writer, addr):
    uuid = msg.get("WORKER_UUID")
    if not uuid:
        logger.warning("Apresentação sem WORKER_UUID ignorada: %s", msg)
        return
    origem = msg.get("SERVER_UUID")          # presente => emprestado
    emprestado = origem is not None
    self.workers.setdefault(uuid, {"emprestado": emprestado, "origem": origem,
                                     "concluidas": 0})
    tipo = f"emprestado (origem {origem})" if emprestado else "local"
    logger.info("Apresentação de Worker %s [%s]", uuid, tipo)

    if self.tasks:
        user = self.tasks.popleft()          # atômico (sem await no meio)
        logger.info("Entregando QUERY (USER=%s) ao Worker %s", user, uuid)
        await messaging.send_message(writer, {"TASK": "QUERY", "USER": user})
    else:
        logger.info("Fila vazia: NO_TASK para Worker %s", uuid)
        await messaging.send_message(writer, {"TASK": "NO_TASK"})
```

Atualizar `run_server` para repassar `tasks`.

- [ ] **Step 3: Rodar os testes (CT01, CT03 passam)**

```bash
cd sprints/sprint02_tarefas && python -m pytest tests/test_tarefas_integration.py -q
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat(sprint-02): Master com fila de tarefas e apresentação (QUERY/NO_TASK)"
```

---

### Task 3: Master — reporte de status (STATUS → ACK + log local/emprestado)

**Files:**
- Modify: `sprints/sprint02_tarefas/src/heartbeat/master_async.py`
- Test: `sprints/sprint02_tarefas/tests/test_tarefas_integration.py` (CT04, CT05, CT02)

- [ ] **Step 1: Escrever testes (CT04 OK→ACK, CT05 NOK→ACK)**

```python
def test_ct04_status_ok_recebe_ack():
    async def cenario():
        m, server = await _abre(9204, [])
        resp = await _presenta(9204, {"STATUS": "OK", "TASK": "QUERY", "WORKER_UUID": "W-123"})
        server.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server
        return resp
    resp = asyncio.run(cenario())
    assert resp["STATUS"] == "ACK"

def test_ct05_status_nok_recebe_ack():
    async def cenario():
        m, server = await _abre(9205, [])
        resp = await _presenta(9205, {"STATUS": "NOK", "TASK": "QUERY", "WORKER_UUID": "W-123"})
        server.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server
        return resp
    resp = asyncio.run(cenario())
    assert resp["STATUS"] == "ACK"
```

- [ ] **Step 2: Implementar tratamento de STATUS**

```python
async def _handle_status(self, msg, writer, addr):
    uuid = msg.get("WORKER_UUID")
    status = msg.get("STATUS")
    if not uuid or status not in ("OK", "NOK"):
        logger.warning("Reporte de status inválido ignorado: %s", msg)
        return
    info = self.workers.get(uuid, {"emprestado": False, "origem": None, "concluidas": 0})
    info["concluidas"] += 1
    self.workers[uuid] = info
    tipo = f"emprestado (origem {info['origem']})" if info["emprestado"] else "local"
    nivel = logger.info if status == "OK" else logger.warning
    nivel("Worker %s [%s] reportou %s na TASK %s (total concluídas: %d)",
          uuid, tipo, status, msg.get("TASK"), info["concluidas"])
    # ACK segue a 'Definição do Payload Padrão' (com WORKER_UUID para correlação)
    await messaging.send_message(writer, {"STATUS": "ACK", "WORKER_UUID": uuid})
```

- [ ] **Step 3: Rodar testes (CT04, CT05 passam)**

```bash
cd sprints/sprint02_tarefas && python -m pytest tests/test_tarefas_integration.py -q
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat(sprint-02): Master trata STATUS (OK/NOK) com ACK e log local/emprestado"
```

---

### Task 4: Worker — apresentação, executor e loop de trabalho

**Files:**
- Modify: `sprints/sprint02_tarefas/src/heartbeat/worker_async.py`
- Test: `sprints/sprint02_tarefas/tests/test_worker_unit.py`

- [ ] **Step 1: Teste de unidade do executor (OK/NOK determinístico)**

```python
import asyncio
from src.heartbeat import worker_async

def test_process_task_ok_quando_forcado():
    res = asyncio.run(worker_async.process_task("Michel", force="OK", min_delay=0, max_delay=0))
    assert res == "OK"

def test_process_task_nok_quando_forcado():
    res = asyncio.run(worker_async.process_task("Julia", force="NOK", min_delay=0, max_delay=0))
    assert res == "NOK"
```

- [ ] **Step 2: Implementar executor + apresentação + loop**

```python
import random

async def process_task(user, force=None, min_delay=0.05, max_delay=0.3):
    """Simula o processamento de uma QUERY e devolve 'OK'/'NOK'.

    `force` permite tornar o resultado determinístico em testes.
    """
    await asyncio.sleep(random.uniform(min_delay, max_delay))
    if force in ("OK", "NOK"):
        return force
    return "OK" if random.random() > 0.1 else "NOK"   # ~10% de falha simulada


async def present(reader, writer, worker_uuid, origin_master=None):
    payload = {"WORKER": "ALIVE", "WORKER_UUID": worker_uuid}
    if origin_master:                      # worker emprestado
        payload["SERVER_UUID"] = origin_master
    await messaging.send_message(writer, payload)
    return await asyncio.wait_for(messaging.read_message(reader),
                                  timeout=RESPONSE_TIMEOUT)


async def do_one_task(host, port, worker_uuid, origin_master=None):
    """Um ciclo completo: present -> QUERY/NO_TASK -> (processa, reporta, ACK)."""
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
                logger.info("ACK recebido — ciclo concluído (status enviado: %s)", status)
                return status
            logger.warning("ACK não recebido como esperado: %s", ack)
            return status
        logger.warning("Resposta inesperada do Master: %s", resp)
        return None
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def work_loop(host, port, worker_uuid, origin_master=None,
                    interval=2.0):
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
```

Adicionar `import contextlib` no topo. Atualizar `main()` para aceitar
`--uuid` e `--origin-master` e chamar `work_loop`.

- [ ] **Step 3: Rodar testes de unidade**

```bash
cd sprints/sprint02_tarefas && python -m pytest tests/test_worker_unit.py -q
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat(sprint-02): Worker com apresentação, executor e loop de trabalho"
```

---

### Task 5: Teste end-to-end (ciclo completo) + CT02 (emprestado)

**Files:**
- Test: `sprints/sprint02_tarefas/tests/test_tarefas_integration.py`

- [ ] **Step 1: Teste do ciclo completo (present→QUERY→OK→ACK) usando o Worker real**

```python
def test_ciclo_completo_present_query_ok_ack():
    from src.heartbeat import worker_async
    async def cenario():
        m, server = await _abre(9210, ["Michel"])
        # força OK para ser determinístico
        import unittest.mock as mock
        with mock.patch.object(worker_async, "process_task",
                               side_effect=lambda *a, **k: _coro("OK")):
            resultado = await worker_async.do_one_task("127.0.0.1", 9210, "W-123")
        server.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server
        return resultado
    def _coro(v):
        async def _c(): return v
        return _c()
    assert asyncio.run(cenario()) == "OK"

def test_ct02_worker_emprestado_recebe_query():
    async def cenario():
        m, server = await _abre(9202, ["Julia"])
        resp = await _presenta(9202, {"WORKER": "ALIVE", "WORKER_UUID": "W-999",
                                       "SERVER_UUID": "Master-B"})
        emprestado = m.workers.get("W-999", {}).get("emprestado")
        server.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server
        return resp, emprestado
    resp, emprestado = asyncio.run(cenario())
    assert resp["TASK"] == "QUERY" and resp["USER"] == "Julia"
    assert emprestado is True
```

- [ ] **Step 2: Rodar a suíte completa**

```bash
cd sprints/sprint02_tarefas && python -m pytest -q
```

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "test(sprint-02): ciclo completo end-to-end e CT02 (worker emprestado)"
```

---

### Task 6: Entrypoints, runner standalone, README e demo

**Files:**
- Modify: `sprints/sprint02_tarefas/master.py`, `worker.py`
- Modify: `sprints/sprint02_tarefas/run_tests.py` (incluir os novos módulos de teste)
- Create: `sprints/sprint02_tarefas/scripts/run_tarefas_demo.py`
- Create/Update: `sprints/sprint02_tarefas/README.md`

- [ ] **Step 1: Atualizar entrypoints** — `master.py` passa `--tasks`; `worker.py` passa `--uuid`/`--origin-master`.

- [ ] **Step 2: Atualizar `run_tests.py`** para listar `tests.test_messaging_sprint02`, `tests.test_tarefas_integration`, `tests.test_worker_unit` (além dos da Sprint 01).

- [ ] **Step 3: Demo automática** (`scripts/run_tarefas_demo.py`): sobe Master com `["Michel","Julia"]`, roda o Worker por alguns ciclos e mostra QUERY→OK→ACK e depois NO_TASK.

- [ ] **Step 4: README.md** com payloads, como rodar (`python master.py --tasks Michel,Julia` / `python worker.py --uuid W-123`), e checklist do DoD (1–5).

- [ ] **Step 5: Verificação final**

```bash
cd sprints/sprint02_tarefas && python run_tests.py          # tudo verde (Sprint 01 + 02)
python scripts/run_tarefas_demo.py                          # demo do ciclo
```

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "docs(sprint-02): entrypoints, demo, README e runner atualizados"
```

---

## Self-review

- **Cobertura da spec:** apresentação local/emprestado (Tarefa 01), fila +
  QUERY/NO_TASK (Tarefa 02), executor + STATUS (Tarefa 03), ACK + log (Tarefa
  04). DoD 1–5 coberto pelos testes CT01–CT05 + ciclo completo.
- **Sem placeholders:** todos os passos têm caminho de arquivo, código e comando.
- **Reaproveitamento:** `messaging.py` e o `HEARTBEAT` da Sprint 01 ficam
  intactos; a Sprint 02 só adiciona.
- **Ponto aberto registrado:** formato do ACK (com/sem `WORKER_UUID`) — decisão
  documentada na spec; troca trivial se o avaliador exigir o formato "pelado".

## Execução

Após sua revisão, posso executar este plano aqui (implementar + rodar os testes)
e te entregar a pasta `sprints/sprint02_tarefas/` pronta, com o resumo de testes
e os comandos de commit. Diga `executar` para eu seguir, ou aponte ajustes.
