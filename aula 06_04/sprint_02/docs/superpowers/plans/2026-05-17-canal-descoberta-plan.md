# Canal de Descoberta Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

I'm using the writing-plans skill to create the implementation plan.

**Goal:** Implementar o Canal de Descoberta (UDP multicast/broadcast) para que Workers descubram Masters na LAN com janela de coleta de respostas configurável (padrão: 3000ms).

**Architecture:** Módulos isolados `src/discovery/worker_discovery.py` e `src/discovery/master_discovery.py`. Testes unitários para serialização/parsing e testes de integração que executam um Master responder em thread local.

**Tech Stack:** Python 3.x, sockets UDP, `pytest` (preferido). Git para versionamento.

---

## File structure (o que será criado/modificado)

- Create: `src/discovery/__init__.py`
- Create: `src/discovery/worker_discovery.py`
- Create: `src/discovery/master_discovery.py`
- Create: `tests/test_discovery_serialization.py`
- Create: `tests/test_worker_discovery_integration.py`
- Create: `docs/operacao/tarefa01-runbook.md`

---

### Task 1: Testes de serialização (rápido)

**Files:**
- Create: `tests/test_discovery_serialization.py`

- [ ] **Step 1: Escrever teste que falhe**

```python
# tests/test_discovery_serialization.py
import json
from src.discovery.worker_discovery import make_discovery_message, parse_response

def test_serialization_roundtrip():
    msg = make_discovery_message(worker_id='test-worker', hostname='host', reply_port=12345)
    assert isinstance(msg, bytes)
    obj = json.loads(msg.decode('utf-8'))
    assert obj['type'] == 'discovery' and obj['version'] == 1

    # resposta de exemplo
    resp = {
        'type': 'discovery_response',
        'version': 1,
        'master_id': 'master-1',
        'hostname': 'master01'
    }
    data = json.dumps(resp).encode('utf-8')
    parsed = parse_response(data)
    assert parsed['master_id'] == 'master-1'
```

- [ ] **Step 2: Rodar teste para verificar que falha**

```bash
pytest tests/test_discovery_serialization.py -q || true
```

Esperado: FAIL (ainda não existe `src.discovery.worker_discovery` e funções)

- [ ] **Step 3: Implementação mínima para passar o teste**

```python
# src/discovery/worker_discovery.py
import json
import socket
import uuid
import os

def make_discovery_message(worker_id=None, hostname=None, reply_port=None):
    payload = {
        'type': 'discovery',
        'version': 1,
        'worker_id': worker_id or str(uuid.uuid4()),
        'hostname': hostname or socket.gethostname(),
        'reply_port': int(reply_port) if reply_port is not None else None
    }
    return json.dumps(payload).encode('utf-8')

def parse_response(data_bytes):
    return json.loads(data_bytes.decode('utf-8'))
```

- [ ] **Step 4: Rodar o teste e esperar PASS**

```bash
pytest tests/test_discovery_serialization.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/discovery/worker_discovery.py tests/test_discovery_serialization.py
git commit -m "test(discovery): add serialization tests and minimal impl"
```

---

### Task 2: Implementação mínima do Worker (discover_masters)

**Files:**
- Create: `src/discovery/worker_discovery.py` (extend)
- Test: `tests/test_worker_discovery_integration.py`

- [ ] **Step 1: Escrever teste de integração que falhe**

```python
# tests/test_worker_discovery_integration.py
import threading
import time
from src.discovery.worker_discovery import discover_masters
from src.discovery.master_discovery import MasterResponder

def run_master():
    m = MasterResponder(group='239.255.0.1', port=50000, mode='multicast')
    m.start()
    time.sleep(3)
    m.stop()

def test_worker_discovers_master():
    t = threading.Thread(target=run_master, daemon=True)
    t.start()
    responses = discover_masters(timeout_ms=2000, group='239.255.0.1', port=50000, mode='multicast')
    assert isinstance(responses, list)
    assert any(r.get('type') == 'discovery_response' and r.get('master_id') for r in responses)
```

- [ ] **Step 2: Rodar teste (deverá FAIL)**

```bash
pytest tests/test_worker_discovery_integration.py -q || true
```

- [ ] **Step 3: Implementar `discover_masters` (mínimo funcional)**

```python
# src/discovery/worker_discovery.py (adicionar ao arquivo existente)
import struct
import time

def discover_masters(timeout_ms=3000, group='239.255.0.1', port=50000, mode='multicast'):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout_ms / 1000.0)
    # bind em porta efêmera para receber respostas
    s.bind(('', 0))
    reply_port = s.getsockname()[1]
    msg = make_discovery_message(reply_port=reply_port)

    if mode == 'multicast':
        # definir TTL
        ttl = int(os.getenv('DISCOVERY_TTL', '1'))
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
        except Exception:
            pass
        s.sendto(msg, (group, port))
    else:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(msg, ('255.255.255.255', port))

    end = time.time() + (timeout_ms / 1000.0)
    responses = []
    while time.time() < end:
        try:
            data, addr = s.recvfrom(4096)
            responses.append(parse_response(data))
        except socket.timeout:
            break
        except Exception:
            continue
    s.close()
    return responses
```

- [ ] **Step 4: Rodar teste de integração e esperar PASS**

```bash
pytest tests/test_worker_discovery_integration.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/discovery/worker_discovery.py tests/test_worker_discovery_integration.py
git commit -m "feat(discovery): worker discovery implementation + integration test"
```

---

### Task 3: Implementação mínima do Master (responder)

**Files:**
- Create: `src/discovery/master_discovery.py`

- [ ] **Step 1: Escrever/implementar MasterResponder mínimo**

```python
# src/discovery/master_discovery.py
import socket
import json
import struct
import threading
import socket

class MasterResponder:
    def __init__(self, group='239.255.0.1', port=50000, mode='multicast'):
        self.group = group
        self.port = port
        self.mode = mode
        self._sock = None
        self._running = False

    def start(self):
        self._running = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(('', self.port))
        if self.mode == 'multicast':
            try:
                mreq = struct.pack('4sL', socket.inet_aton(self.group), socket.INADDR_ANY)
                self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            except Exception:
                pass
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running:
            try:
                data, addr = self._sock.recvfrom(4096)
            except Exception:
                continue
            try:
                msg = json.loads(data.decode('utf-8'))
            except Exception:
                continue
            if msg.get('type') != 'discovery':
                continue
            reply_port = msg.get('reply_port') or addr[1]
            resp = {
                'type': 'discovery_response',
                'version': 1,
                'master_id': 'master-local-1',
                'hostname': socket.gethostname()
            }
            try:
                self._sock.sendto(json.dumps(resp).encode('utf-8'), (addr[0], reply_port))
            except Exception:
                pass

    def stop(self):
        self._running = False
        try:
            self._sock.close()
        except Exception:
            pass
        if hasattr(self, '_thread'):
            self._thread.join(timeout=1)
```

- [ ] **Step 2: Rodar a suíte de integração novamente**

```bash
pytest tests/test_worker_discovery_integration.py -q
```

- [ ] **Step 3: Commit**

```bash
git add src/discovery/master_discovery.py
git commit -m "feat(discovery): master responder implementation"
```

---

### Task 4: Runbook e documentação (Tarefa 03)

**Files:**
- Create: `docs/operacao/tarefa01-runbook.md`

- [ ] **Step 1: Criar runbook com comandos de verificação e rollback**

Conteúdo mínimo do runbook:
- Como executar localmente:

```bash
# abrir um terminal para master
python -c "from src.discovery.master_discovery import MasterResponder; m=MasterResponder(); m.start(); input('press enter to stop'); m.stop()"
# abrir outro terminal para worker
python -c "from src.discovery.worker_discovery import discover_masters; print(discover_masters(timeout_ms=3000))"
```

- Critérios de sucesso: worker recebe >=1 resposta dentro do timeout
- Rollback: reverter branch/PR

- [ ] **Step 2: Commit docs**

```bash
git add docs/operacao/tarefa01-runbook.md
git commit -m "docs: runbook para Canal de Descoberta"
```

---

## Pre-merge checklist
- [ ] Rodar linters (se aplicável)
- [ ] Rodar `pytest` completo
- [ ] Escrever descrição no PR com instruções para reproduzir localmente

---

## Observações e notas de execução
- Use `DISCOVERY_MODE` env var para alternar entre `multicast` e `broadcast` durante testes.
- Se a máquina estiver em rede que bloqueia multicast, usar `broadcast` para testes locais.
- Tests que usam rede podem ter flakiness; aumentar timeouts para CI flake mitigation.

---

Update (2026-05-17): Implemented TCP election handshake and deterministic election rule.
- `src/discovery/master_discovery.py` now exposes a TCP server (`tcp_port`, default 50010) that responds to `ELECTION` messages with `ELECTION_ACK`.
- `src/discovery/worker_discovery.py` includes `elect_master()` and `perform_discovery_and_election()` which select master by lexicographic order and perform the TCP handshake.
- Integration tests added: `tests/test_worker_election_integration.py`.

---

Arquivo salvo em: `docs/superpowers/plans/2026-05-17-canal-descoberta-plan.md`
