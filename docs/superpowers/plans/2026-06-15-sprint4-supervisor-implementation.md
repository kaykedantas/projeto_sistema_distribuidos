# Sprint 4 — Supervisor de Métricas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o Master (raiz) coletar métricas de sistema (psutil) e de farm e enviá-las a cada 10s ao Supervisor de Métricas via TLS sobre TCP, no schema `performance_report` do PDF.

**Architecture:** Tudo embutido no `master.py` consolidado, numa seção "Sprint 4 — Supervisor": um builder de payload (função pura), um sender TLS fire-and-forget e um loop asyncio em background disparado no `start()`. Estado novo no Master (contadores e timestamps de fila) alimenta o `farm_state`.

**Tech Stack:** Python 3.8+ stdlib (`asyncio`, `ssl`, `socket`, `json`, `datetime`) + `psutil` (obrigatório).

> **Nota sobre commits:** os passos de `git commit` seguem a metodologia, mas só devem ser executados **com autorização do usuário** (o projeto está na branch `Projeto_final`). Na execução, confirme antes de commitar.

> **Nota sobre testes:** o projeto não usa pytest. Os testes ficam em `test_supervisor.py` (raiz) com um runner próprio (igual a `test_task_recovery.py`). Cada passo "rodar teste" executa `python test_supervisor.py`.

---

## File Structure

- **Modify:** `master.py` (raiz) — imports, constantes, classe `Master` (estado + helpers + handlers), funções de coleta/builder/sender, `_supervisor_loop`, `run_server`, `main`.
- **Create:** `requirements.txt` (raiz) — declara `psutil`.
- **Create:** `test_supervisor.py` (raiz) — testes do builder, contadores, idade de tarefa e sender.

---

## Task 1: Setup — requirements, imports e constantes

**Files:**
- Create: `requirements.txt`
- Modify: `master.py` (bloco de imports e bloco "CONFIGURAÇÃO RÁPIDA")

- [ ] **Step 1: Criar `requirements.txt` na raiz**

```text
# Sprint 4 — coleta de métricas de sistema
psutil>=5.9
```

- [ ] **Step 2: Adicionar imports no topo do `master.py`**

Localize o bloco de imports (após o docstring/constantes, onde estão `import asyncio`, `import json`, etc.) e adicione:

```python
import os
import ssl
import time
from datetime import datetime, timezone

try:
    import psutil
except ImportError:                      # supervisor degrada sem derrubar o Master
    psutil = None
```

- [ ] **Step 3: Adicionar constantes do supervisor no bloco "CONFIGURAÇÃO RÁPIDA"**

Logo após `DEFAULT_MAX_TASK_ATTEMPTS`:

```python
# ---- Sprint 4: Supervisor de Métricas ----
DEFAULT_SUPERVISOR_UUID     = "michel_1"     # server_uuid no payload (≠ master_id MASTER_9)
DEFAULT_SUPERVISOR_HOST     = "nuted-ia.dev" # host do supervisor
DEFAULT_SUPERVISOR_PORT     = 443            # TLS sobre TCP
DEFAULT_SUPERVISOR_INTERVAL = 10.0           # segundos entre relatórios
DEFAULT_WARN_CPU            = 85             # config_thresholds.warn_cpu_percent
DEFAULT_WARN_MEM            = 85             # config_thresholds.warn_memory_percent
```

- [ ] **Step 4: Verificar import**

Run: `python -c "import master; print('ok', master.DEFAULT_SUPERVISOR_HOST)"`
Expected: `ok nuted-ia.dev`

- [ ] **Step 5: Commit** (com autorização)

```bash
git add requirements.txt master.py
git commit -m "feat(sprint4): setup de imports, psutil e constantes do supervisor"
```

---

## Task 2: Estado novo + helpers de fila com timestamps

Adiciona contadores e a deque paralela de tempos, e centraliza as mutações de `self.tasks` em helpers (também limpa o código at-least-once da Sprint 3.2). Habilita `oldest_task_age_s`.

**Files:**
- Modify: `master.py` (`Master.__init__`, novos métodos; substituições em `_handle_apresentacao`, `_requeue_if_inflight`, `_requeue_task`, `_stdin_task_feeder`)
- Create/Modify: `test_supervisor.py`

- [ ] **Step 1: Escrever o teste (cria `test_supervisor.py`)**

```python
"""test_supervisor.py — Testes da Sprint 4 (Supervisor de Métricas) no master.py raiz."""
import asyncio
import contextlib
import time
from collections import deque

import master as M


def test_oldest_task_age_cresce_e_zera():
    m = M.Master("127.0.0.1", 0, master_id="MASTER_9", tasks=["T1"])
    # força o timestamp da T1 para 5s atrás
    m.task_times[0] = time.time() - 5
    assert m.oldest_task_age_s() >= 5
    # ao consumir a única tarefa, idade volta a 0
    assert m._dequeue() == "T1"
    assert m.oldest_task_age_s() == 0


def test_enqueue_front_mantem_sincronia():
    m = M.Master("127.0.0.1", 0, master_id="MASTER_9", tasks=[])
    m._enqueue("A")
    m._enqueue("B")
    m._enqueue_front("C")              # C vai para a frente (reenfileiramento)
    assert list(m.tasks) == ["C", "A", "B"]
    assert len(m.task_times) == 3      # deque de tempos permanece alinhada
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python test_supervisor.py`
Expected: FAIL (`AttributeError: 'Master' object has no attribute 'task_times'` / `oldest_task_age_s`)

- [ ] **Step 3: Adicionar estado no `Master.__init__`**

Após a linha `self.in_flight = {}` / `self.task_attempts = {}` (estado da Sprint 3.2), adicione:

```python
        # Sprint 4: contadores e timestamps para o performance_report
        self._start_time = time.time()
        self.tasks_completed = 0
        self.tasks_failed = 0
        self.workers_failed = 0
        # deque paralela a self.tasks com o instante de enfileiramento de cada tarefa
        self.task_times = deque(time.time() for _ in self.tasks)
```

E logo abaixo das configs de capacity/release no `__init__`, guarde os parâmetros do supervisor (serão adicionados à assinatura na Task 7; por ora use os defaults do módulo):

```python
        self.supervisor_uuid = DEFAULT_SUPERVISOR_UUID
        self.supervisor_host = DEFAULT_SUPERVISOR_HOST
        self.supervisor_port = DEFAULT_SUPERVISOR_PORT
        self.supervisor_interval = DEFAULT_SUPERVISOR_INTERVAL
        self.supervisor_enabled = True
        self.warn_cpu_percent = DEFAULT_WARN_CPU
        self.warn_memory_percent = DEFAULT_WARN_MEM
```

- [ ] **Step 4: Adicionar os helpers de fila na classe `Master`**

Junto aos métodos de tolerância a falhas (perto de `_requeue_task`):

```python
    # ── Fila de tarefas com timestamps (Sprint 4) ───────────────

    def _enqueue(self, user) -> None:
        """Adiciona nova tarefa ao fim da fila."""
        self.tasks.append(user)
        self.task_times.append(time.time())

    def _enqueue_front(self, user) -> None:
        """Devolve tarefa à frente da fila (reenfileiramento)."""
        self.tasks.appendleft(user)
        self.task_times.appendleft(time.time())

    def _dequeue(self):
        """Retira a próxima tarefa (FIFO), mantendo task_times em sincronia."""
        user = self.tasks.popleft()
        if self.task_times:
            self.task_times.popleft()
        return user

    def oldest_task_age_s(self) -> int:
        """Idade (s) da tarefa pendente mais antiga; 0 se a fila está vazia."""
        if not self.task_times:
            return 0
        return int(time.time() - self.task_times[0])
```

- [ ] **Step 5: Trocar as mutações diretas de `self.tasks` pelos helpers**

Em `_handle_apresentacao`, trocar:
```python
            user = self.tasks.popleft()
```
por:
```python
            user = self._dequeue()
```

Em `_requeue_if_inflight`, trocar `self.tasks.appendleft(user)` por `self._enqueue_front(user)`.

Em `_requeue_task`, trocar `self.tasks.appendleft(user)` por `self._enqueue_front(user)`.

Em `_stdin_task_feeder`, trocar `self.tasks.append(cmd)` por `self._enqueue(cmd)`.

- [ ] **Step 6: Rodar e ver passar**

Run: `python test_supervisor.py`
Expected: PASS (2/2 até aqui)

- [ ] **Step 7: Garantir que a Sprint 3.2 não regrediu**

Run: `python test_task_recovery.py`
Expected: `4/4 testes passaram`

- [ ] **Step 8: Commit** (com autorização)

```bash
git add master.py test_supervisor.py
git commit -m "feat(sprint4): estado de métricas e fila com timestamps"
```

---

## Task 3: Contadores tasks_completed / tasks_failed / workers_failed

**Files:**
- Modify: `master.py` (`_handle_status`, `_requeue_if_inflight`)
- Modify: `test_supervisor.py`

- [ ] **Step 1: Escrever o teste (adicionar a `test_supervisor.py`)**

```python
async def _sobe(m):
    server = await asyncio.start_server(m.handle_client, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def _ciclo_status(port, status):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    await M.send_message(writer, {"WORKER": "ALIVE", "WORKER_UUID": "W1"})
    await asyncio.wait_for(M.read_message(reader), timeout=2)         # QUERY
    await M.send_message(writer, {"STATUS": status, "TASK": "QUERY", "WORKER_UUID": "W1"})
    await asyncio.wait_for(M.read_message(reader), timeout=2)         # ACK
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()


def test_contadores_ok_e_nok():
    async def cenario():
        m = M.Master("127.0.0.1", 0, master_id="MASTER_9", tasks=["T1", "T2"],
                     max_task_attempts=5)
        server, port = await _sobe(m)
        await _ciclo_status(port, "OK")
        await _ciclo_status(port, "NOK")
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
        return m
    m = asyncio.run(cenario())
    assert m.tasks_completed == 1, m.tasks_completed
    assert m.tasks_failed == 1, m.tasks_failed
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python test_supervisor.py`
Expected: FAIL (`assert 0 == 1` — contadores ainda não incrementam)

- [ ] **Step 3: Incrementar contadores em `_handle_status`**

No bloco que trata OK/NOK (Sprint 3.2), ajustar para:

```python
        if status == "OK":
            self.tasks_completed += 1
            if user is not None:
                self.task_attempts.pop(user, None)  # tarefa concluída: zera tentativas
        else:  # NOK -> retentar com limite (dead-letter ao exceder)
            self.tasks_failed += 1
            if user is not None:
                self._requeue_task(user, motivo="NOK")
```

- [ ] **Step 4: Contar worker que cai com tarefa em andamento em `_requeue_if_inflight`**

Após `self.tasks` receber a tarefa de volta (antes do `logger.warning`), adicionar:

```python
        self.workers_failed += 1
```

- [ ] **Step 5: Rodar e ver passar**

Run: `python test_supervisor.py`
Expected: PASS (3/3)

- [ ] **Step 6: Commit** (com autorização)

```bash
git add master.py test_supervisor.py
git commit -m "feat(sprint4): contadores de tarefas concluídas/falhas e workers caídos"
```

---

## Task 4: Coleta de métricas de sistema (psutil)

**Files:**
- Modify: `master.py` (nova seção "Sprint 4 — Supervisor", função `_collect_system_metrics`)
- Modify: `test_supervisor.py`

- [ ] **Step 1: Escrever o teste (com psutil mockado)**

```python
class _FakePsutil:
    def virtual_memory(self):
        class V: total = 16 * 1024**3; available = 8 * 1024**3; percent = 50.0
        return V()
    def disk_usage(self, _):
        class D: total = 512 * 1024**3; free = 256 * 1024**3; percent = 50.0
        return D()
    def getloadavg(self): return (1.0, 2.0, 3.0)
    def cpu_percent(self): return 42.5
    def cpu_count(self, logical=True): return 8 if logical else 4


def test_collect_system_metrics():
    orig = M.psutil
    M.psutil = _FakePsutil()
    try:
        s = M._collect_system_metrics(time.time() - 100)
    finally:
        M.psutil = orig
    assert s["uptime_seconds"] >= 100
    assert s["cpu"] == {"usage_percent": 42.5, "count_logical": 8, "count_physical": 4}
    assert s["memory"]["total_mb"] == 16384
    assert s["memory"]["memory_used"] == 8192
    assert s["disk"]["total_gb"] == 512.0
    assert s["load_average_1m"] == 1.0 and s["load_average_5m"] == 2.0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python test_supervisor.py`
Expected: FAIL (`AttributeError: module 'master' has no attribute '_collect_system_metrics'`)

- [ ] **Step 3: Implementar `_collect_system_metrics`**

Adicionar uma nova seção no `master.py` (após a classe `Master` ou antes de `run_server`):

```python
# ────────────────────────────────────────────────────────────────
# Sprint 4 — Supervisor de Métricas (performance_report)
# ────────────────────────────────────────────────────────────────

def _collect_system_metrics(start_time: float) -> dict:
    """Coleta CPU/memória/disco/load via psutil. Requer psutil instalado."""
    vm = psutil.virtual_memory()
    du = psutil.disk_usage(os.path.abspath(os.sep))
    try:
        la1, la5, _ = psutil.getloadavg()
    except (OSError, AttributeError):
        la1 = la5 = 0.0
    return {
        "uptime_seconds": int(time.time() - start_time),
        "load_average_1m": round(la1, 2),
        "load_average_5m": round(la5, 2),
        "cpu": {
            "usage_percent": round(psutil.cpu_percent(), 2),
            "count_logical": psutil.cpu_count(logical=True) or 0,
            "count_physical": psutil.cpu_count(logical=False) or 0,
        },
        "memory": {
            "total_mb": vm.total // (1024 * 1024),
            "available_mb": vm.available // (1024 * 1024),
            "percent_used": round(vm.percent, 2),
            "memory_used": (vm.total - vm.available) // (1024 * 1024),
        },
        "disk": {
            "total_gb": round(du.total / (1024 ** 3), 1),
            "free_gb": round(du.free / (1024 ** 3), 1),
            "percent_used": round(du.percent, 1),
        },
    }
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python test_supervisor.py`
Expected: PASS (4/4)

- [ ] **Step 5: Commit** (com autorização)

```bash
git add master.py test_supervisor.py
git commit -m "feat(sprint4): coleta de métricas de sistema via psutil"
```

---

## Task 5: Builder do payload (`build_performance_report`)

**Files:**
- Modify: `master.py` (funções `_build_farm_state`, `_build_neighbors`, `build_performance_report`)
- Modify: `test_supervisor.py`

- [ ] **Step 1: Escrever o teste (estado de farm conhecido)**

```python
def test_build_performance_report_estrutura_e_mapeamento():
    m = M.Master("127.0.0.1", 0, master_id="MASTER_9", tasks=["T1", "T2"])
    m.supervisor_uuid = "michel_1"
    m.workers = {"W1": {"emprestado": False, "origem": None, "concluidas": 0}}
    m.idle_workers = [{"id": "W1", "address": "ip:1"}]
    m.in_flight = {"W2": "T9"}
    m.lent_out = {"W3": {"para": "MASTER_B"}}
    m.borrowed_in = {"W4": {"origem": "10.0.0.2:7011"}}
    m.tasks_completed, m.tasks_failed = 7, 2
    m.neighbors = {"MASTER_B": ("10.0.0.2", 7011)}

    orig = M.psutil
    M.psutil = _FakePsutil()
    try:
        p = M.build_performance_report(m, neighbor_status={"MASTER_B": True})
    finally:
        M.psutil = orig

    assert p["server_uuid"] == "michel_1"
    assert p["role"] == "master" and p["task"] == "performance_report"
    assert p["payload_version"] == "sprint4-monitor"
    assert p["timestamp"].endswith("Z")
    fs = p["performance"]["farm_state"]
    assert fs["workers"]["total_registered"] == 1
    assert fs["workers"]["workers_idle"] == 1
    assert fs["workers"]["workers_borrowed"] == 1     # lent_out
    assert fs["workers"]["workers_received"] == 1     # borrowed_in
    assert fs["workers"]["workers_utilization"] == 1  # in_flight
    assert {"direction": "out", "peer_uuid": "MASTER_B"} in fs["workers"]["borrowed_workers"]
    assert fs["tasks"]["tasks_pending"] == 2
    assert fs["tasks"]["tasks_completed"] == 7 and fs["tasks"]["tasks_failed"] == 2
    ct = p["performance"]["config_thresholds"]
    assert ct["max_task"] == m.capacity and ct["release_task"] == m.release_threshold
    nb = p["performance"]["neighbors"][0]
    assert nb["server_uuid"] == "MASTER_B" and nb["status"] == "available"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python test_supervisor.py`
Expected: FAIL (`AttributeError: ... 'build_performance_report'`)

- [ ] **Step 3: Implementar farm_state, neighbors e o builder**

Na seção "Sprint 4 — Supervisor", após `_collect_system_metrics`:

```python
def _build_farm_state(master) -> dict:
    total_registered = len(master.workers)
    workers_received = len(master.borrowed_in)
    borrowed = [{"direction": "out", "peer_uuid": info.get("para")}
                for info in master.lent_out.values()]
    borrowed += [{"direction": "in", "peer_uuid": info.get("origem")}
                 for info in master.borrowed_in.values()]
    return {
        "workers": {
            "total_registered": total_registered,
            "workers_utilization": len(master.in_flight),
            "workers_alive": total_registered,
            "workers_idle": len(master.idle_workers),
            "workers_borrowed": len(master.lent_out),
            "workers_received": workers_received,
            "workers_failed": master.workers_failed,
            "workers_home": total_registered - workers_received,
            "workers_available_capacity": len(master.idle_workers),
            "borrowed_workers": borrowed,
        },
        "tasks": {
            "tasks_pending": len(master.tasks),
            "tasks_running": len(master.in_flight),
            "tasks_completed": master.tasks_completed,
            "tasks_failed": master.tasks_failed,
            "oldest_task_age_s": master.oldest_task_age_s(),
        },
    }


def _build_neighbors(master, neighbor_status) -> list:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for nid in master.neighbors:
        ok = bool((neighbor_status or {}).get(nid))
        out.append({
            "server_uuid": nid,
            "status": "available" if ok else "unavailable",
            "last_heartbeat": now if ok else None,
        })
    return out


def build_performance_report(master, neighbor_status=None) -> dict:
    """Monta o payload performance_report (função pura; psutil é lido aqui)."""
    return {
        "server_uuid": master.supervisor_uuid,
        "hostname": socket.gethostname(),
        "role": "master",
        "task": "performance_report",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "message_id": str(uuid.uuid4()),
        "payload_version": "sprint4-monitor",
        "performance": {
            "system": _collect_system_metrics(master._start_time),
            "farm_state": _build_farm_state(master),
            "config_thresholds": {
                "max_task": master.capacity,
                "warn_cpu_percent": master.warn_cpu_percent,
                "warn_memory_percent": master.warn_memory_percent,
                "release_task": master.release_threshold,
            },
            "neighbors": _build_neighbors(master, neighbor_status),
        },
    }
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python test_supervisor.py`
Expected: PASS (5/5)

- [ ] **Step 5: Commit** (com autorização)

```bash
git add master.py test_supervisor.py
git commit -m "feat(sprint4): builder do performance_report"
```

---

## Task 6: Sender TLS fire-and-forget resiliente

**Files:**
- Modify: `master.py` (`send_report_tls`)
- Modify: `test_supervisor.py`

- [ ] **Step 1: Escrever o teste (host inalcançável não lança)**

```python
def test_send_report_tls_engole_falha():
    async def cenario():
        # porta 1 fechada -> conexão falha; a função NÃO pode lançar
        await M.send_report_tls({"x": 1}, "127.0.0.1", 1, timeout=1.0)
        return True
    assert asyncio.run(cenario()) is True
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python test_supervisor.py`
Expected: FAIL (`AttributeError: ... 'send_report_tls'`)

- [ ] **Step 3: Implementar `send_report_tls`**

Na seção "Sprint 4 — Supervisor":

```python
async def send_report_tls(payload: dict, host: str, port: int,
                          sni: str = None, timeout: float = 5.0) -> None:
    """Fire-and-forget: abre TLS, envia JSON+\\n e fecha. Engole falhas (loga)."""
    data = encode_message(payload)        # json + \n (mesma serialização do projeto)
    ctx = ssl.create_default_context()
    writer = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx,
                                    server_hostname=sni or host),
            timeout=timeout)
        writer.write(data)
        await writer.drain()
        logger.info("supervisor: relatório enviado a %s:%s (%d bytes)",
                    host, port, len(data))
    except (asyncio.TimeoutError, OSError, ssl.SSLError) as e:
        logger.warning("supervisor: envio a %s:%s falhou (%s)", host, port, e)
    finally:
        if writer is not None:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python test_supervisor.py`
Expected: PASS (6/6)

- [ ] **Step 5: Commit** (com autorização)

```bash
git add master.py test_supervisor.py
git commit -m "feat(sprint4): sender TLS fire-and-forget resiliente"
```

---

## Task 7: Loop em background + integração (start, run_server, CLI)

**Files:**
- Modify: `master.py` (`Master._probe_neighbors`, `Master._supervisor_loop`, `Master.start`, `Master.__init__` assinatura, `run_server`, `main`)

- [ ] **Step 1: Adicionar `_probe_neighbors` e `_supervisor_loop` na classe `Master`**

```python
    # ── Sprint 4: loop do supervisor ─────────────────────────────

    async def _probe_neighbors(self) -> dict:
        """Checa alcançabilidade TCP de cada vizinho (status no relatório)."""
        status = {}
        for nid in list(self.neighbors):
            status[nid] = await self._try_connect_neighbor(nid)
        return status

    async def _supervisor_loop(self) -> None:
        """A cada supervisor_interval: monta e envia o performance_report."""
        logger.info("supervisor: relatórios a cada %.0fs -> %s:%s (uuid=%s)",
                    self.supervisor_interval, self.supervisor_host,
                    self.supervisor_port, self.supervisor_uuid)
        while True:
            try:
                neighbor_status = await self._probe_neighbors()
                payload = build_performance_report(self, neighbor_status)
                await send_report_tls(payload, self.supervisor_host,
                                      self.supervisor_port, sni=self.supervisor_host)
            except Exception:
                logger.warning("supervisor: ciclo falhou (ignorado)", exc_info=False)
            await asyncio.sleep(self.supervisor_interval)
```

- [ ] **Step 2: Disparar o loop no `start()`**

Trocar o `asyncio.gather(...)` final de `start()` por:

```python
        async with self._server:
            coros = [self._server.serve_forever(), self._stdin_task_feeder()]
            if self.supervisor_enabled and psutil is not None:
                coros.append(self._supervisor_loop())
            elif self.supervisor_enabled and psutil is None:
                logger.warning("psutil não instalado (pip install -r requirements.txt); "
                               "supervisor desativado")
            await asyncio.gather(*coros)
```

- [ ] **Step 3: Adicionar parâmetros do supervisor à assinatura de `__init__`**

Adicionar ao final dos parâmetros de `__init__` (após `max_task_attempts`):

```python
                 supervisor_uuid: str = DEFAULT_SUPERVISOR_UUID,
                 supervisor_host: str = DEFAULT_SUPERVISOR_HOST,
                 supervisor_port: int = DEFAULT_SUPERVISOR_PORT,
                 supervisor_interval: float = DEFAULT_SUPERVISOR_INTERVAL,
                 supervisor_enabled: bool = True,
                 warn_cpu_percent: int = DEFAULT_WARN_CPU,
                 warn_memory_percent: int = DEFAULT_WARN_MEM):
```

E no corpo, substituir as atribuições "por ora use os defaults" (Task 2 Step 3) por:

```python
        self.supervisor_uuid = supervisor_uuid
        self.supervisor_host = supervisor_host
        self.supervisor_port = supervisor_port
        self.supervisor_interval = supervisor_interval
        self.supervisor_enabled = supervisor_enabled
        self.warn_cpu_percent = warn_cpu_percent
        self.warn_memory_percent = warn_memory_percent
```

- [ ] **Step 4: Encaminhar parâmetros em `run_server`**

Adicionar à assinatura de `run_server` (após `max_task_attempts`):

```python
                     supervisor_uuid: str = DEFAULT_SUPERVISOR_UUID,
                     supervisor_host: str = DEFAULT_SUPERVISOR_HOST,
                     supervisor_port: int = DEFAULT_SUPERVISOR_PORT,
                     supervisor_interval: float = DEFAULT_SUPERVISOR_INTERVAL,
                     supervisor_enabled: bool = True,
                     warn_cpu_percent: int = DEFAULT_WARN_CPU,
                     warn_memory_percent: int = DEFAULT_WARN_MEM,
```

E passar ao construtor `Master(...)`:

```python
    m = Master(host, port, master_id, tasks=tasks, name=name,
               advertise_ip=advertise_ip, capacity=capacity,
               release_threshold=release_threshold,
               max_task_attempts=max_task_attempts,
               supervisor_uuid=supervisor_uuid, supervisor_host=supervisor_host,
               supervisor_port=supervisor_port, supervisor_interval=supervisor_interval,
               supervisor_enabled=supervisor_enabled,
               warn_cpu_percent=warn_cpu_percent, warn_memory_percent=warn_memory_percent)
```

- [ ] **Step 5: Adicionar flags na CLI (`main`)**

Após `--max-attempts`:

```python
    parser.add_argument("--supervisor-uuid", default=DEFAULT_SUPERVISOR_UUID,
                        help=f"server_uuid no payload do supervisor (padrão: {DEFAULT_SUPERVISOR_UUID})")
    parser.add_argument("--supervisor-host", default=DEFAULT_SUPERVISOR_HOST,
                        help=f"host do supervisor (padrão: {DEFAULT_SUPERVISOR_HOST})")
    parser.add_argument("--supervisor-port", type=int, default=DEFAULT_SUPERVISOR_PORT,
                        help=f"porta TLS do supervisor (padrão: {DEFAULT_SUPERVISOR_PORT})")
    parser.add_argument("--supervisor-interval", type=float, default=DEFAULT_SUPERVISOR_INTERVAL,
                        help=f"segundos entre relatórios (padrão: {DEFAULT_SUPERVISOR_INTERVAL})")
    parser.add_argument("--no-supervisor", action="store_true",
                        help="desativa o envio de métricas ao supervisor")
    parser.add_argument("--warn-cpu", type=int, default=DEFAULT_WARN_CPU,
                        help=f"limiar de alerta de CPU (padrão: {DEFAULT_WARN_CPU})")
    parser.add_argument("--warn-mem", type=int, default=DEFAULT_WARN_MEM,
                        help=f"limiar de alerta de memória (padrão: {DEFAULT_WARN_MEM})")
```

E no `asyncio.run(run_server(...))`, acrescentar os argumentos:

```python
            supervisor_uuid=args.supervisor_uuid,
            supervisor_host=args.supervisor_host,
            supervisor_port=args.supervisor_port,
            supervisor_interval=args.supervisor_interval,
            supervisor_enabled=not args.no_supervisor,
            warn_cpu_percent=args.warn_cpu,
            warn_memory_percent=args.warn_mem,
```

- [ ] **Step 6: Suíte completa não regrediu**

Run: `python test_supervisor.py` → Expected: PASS (6/6)
Run: `python test_task_recovery.py` → Expected: `4/4 testes passaram`

- [ ] **Step 7: Smoke test offline (sem enviar pra internet)**

Run: `python master.py --no-supervisor --capacity 5 --release-threshold 2` e confirme que o banner sobe normalmente; `Ctrl+C` para sair.
Expected: Master inicia sem erros; nenhuma tentativa de conexão ao supervisor.

- [ ] **Step 8: Commit** (com autorização)

```bash
git add master.py
git commit -m "feat(sprint4): loop do supervisor, integração no start e CLI"
```

---

## Task 8: Verificação manual contra o dashboard (DoD)

**Files:** nenhum (validação em ambiente real, requer internet).

- [ ] **Step 1: Instalar dependência**

Run: `pip install -r requirements.txt`

- [ ] **Step 2: Rodar apontando para o supervisor real**

Run: `python master.py --supervisor-uuid michel_1 --capacity 5 --release-threshold 2`
Expected (log a cada 10s): `supervisor: relatório enviado a nuted-ia.dev:443 (... bytes)`

- [ ] **Step 3: Conferir no dashboard**

Abrir `https://nuted-ia.dev/supervisor/dashboard/` e confirmar que a farm `michel_1`
aparece e atualiza (CPU/memória/disco/tarefas/workers).

- [ ] **Step 4: Atualizar a DoD da spec** marcando os itens cumpridos em
`docs/superpowers/specs/2026-06-15-sprint4-supervisor-design.md`.

---

## Self-Review (preenchido)

**1. Spec coverage:**
- psutil obrigatório + requirements → Task 1. ✅
- Só o Master reporta → Task 7 (loop só no Master). ✅
- Builder puro + mapeamento de todos os blocos → Tasks 4, 5. ✅
- Estado novo (uptime, contadores, timestamps) → Tasks 2, 3. ✅
- TLS fire-and-forget resiliente + config → Tasks 6, 7. ✅
- server_uuid (michel_1) ≠ master_id (MASTER_9) → Task 2/7 (`supervisor_uuid`). ✅
- Aproximações declaradas (workers_alive/failed, last_heartbeat) → Tasks 3, 5. ✅
- Testes (builder, contadores, oldest_task_age, sender) → Tasks 2–6. ✅
- Verificação manual no dashboard → Task 8. ✅

**2. Placeholder scan:** sem TBD/TODO; todos os passos têm código real.

**3. Type consistency:** `build_performance_report(master, neighbor_status)`,
`_collect_system_metrics(start_time)`, `send_report_tls(payload, host, port, sni, timeout)`,
helpers `_enqueue/_enqueue_front/_dequeue/oldest_task_age_s` usados de forma consistente
entre tarefas e testes.
