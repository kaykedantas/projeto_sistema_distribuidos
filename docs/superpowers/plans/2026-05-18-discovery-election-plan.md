# Descoberta e Eleição Implementation Plan

I'm using the writing-plans skill to create the implementation plan.

Goal: Implement the discovery (UDP), deterministic election and TCP handshake described in the spec, with tests and incremental commits.

Architecture: Modular Python packages. Small modules per responsibility: `src/discovery.py`, `src/election.py`, `src/handshake.py`. Tests under `tests/`.

Tech Stack
----------
- Python 3.9+
- pytest for unit tests
- Sockets (stdlib) for UDP/TCP

---

### Task 1: Canal de Descoberta (Discovery)

**Files:**
- Create: `src/discovery.py`
- Test: `tests/test_discovery.py`
- Modify: `woker.py` (import `src.discovery` and call `discover()` where appropriate)

- [ ] **Step 1: Escrever o teste falhando**

`tests/test_discovery.py`:

```python
import json
from src.discovery import make_discovery_payload, parse_discovery_reply

def test_make_discovery_payload_contains_type():
    p = make_discovery_payload("W-101")
    assert b'DISCOVERY' in p

def test_parse_discovery_reply_valid():
    raw = b'{"TYPE":"DISCOVERY_REPLY","MASTER_NAME":"MASTER_1","MASTER_IP":"192.168.1.20","MASTER_PORT":6000,"STATUS":"AVAILABLE"}'
    obj = parse_discovery_reply(raw)
    assert obj['MASTER_NAME'] == 'MASTER_1'
```

- [ ] **Step 2: Rodar teste para ver falhar**

Run:

```bash
pytest tests/test_discovery.py -q
```

- [ ] **Step 3: Implementar código mínimo**

`src/discovery.py` (mínimo para testes):

```python
import json

def make_discovery_payload(worker_uuid: str) -> bytes:
    return json.dumps({"TYPE": "DISCOVERY", "WORKER_UUID": worker_uuid}).encode('utf-8')

def parse_discovery_reply(raw: bytes) -> dict:
    d = json.loads(raw.decode('utf-8'))
    if d.get('TYPE') != 'DISCOVERY_REPLY':
        raise ValueError('invalid type')
    required = ['MASTER_NAME', 'MASTER_IP', 'MASTER_PORT']
    for k in required:
        if k not in d:
            raise ValueError(f'missing {k}')
    return d
```

- [ ] **Step 4: Rodar testes e confirmar pass**

Run:

```bash
pytest tests/test_discovery.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/discovery.py tests/test_discovery.py
git commit -m "feat(discovery): add discovery payload and parser tests"
```

### Task 2: Lógica de Eleição Determinística

**Files:**
- Create: `src/election.py`
- Test: `tests/test_election.py`
- Modify: `woker.py` (invoke election after collecting replies)

- [ ] **Step 1: Escrever o teste falhando**

`tests/test_election.py`:

```python
from src.election import elect_master

def test_elect_master_lexicographic():
    replies = [
        {"MASTER_NAME":"MASTER_2","MASTER_IP":"10.0.0.2"},
        {"MASTER_NAME":"MASTER_1","MASTER_IP":"10.0.0.1"},
    ]
    winner = elect_master(replies)
    assert winner['MASTER_NAME'] == 'MASTER_1'
```

- [ ] **Step 2: Rodar teste (deve falhar)**

```bash
pytest tests/test_election.py -q
```

- [ ] **Step 3: Implementar código mínimo**

`src/election.py`:

```python
from typing import List, Dict, Optional

def elect_master(replies: List[Dict]) -> Optional[Dict]:
    if not replies:
        return None
    sorted_replies = sorted(replies, key=lambda r: (r.get('MASTER_NAME',''), r.get('MASTER_IP','')))
    return sorted_replies[0]
```

- [ ] **Step 4: Rodar testes e confirmar pass**

```bash
pytest tests/test_election.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/election.py tests/test_election.py
git commit -m "feat(election): deterministic master election and tests"
```

### Task 3: Transição UDP → TCP e Handshake Inicial

**Files:**
- Create: `src/handshake.py`
- Test: `tests/test_handshake.py`
- Modify: `woker.py` (abrir conexão TCP com `selected_master` e iniciar Handshake)

- [ ] **Step 1: Escrever o teste falhando (mock)**

`tests/test_handshake.py`:

```python
from unittest.mock import MagicMock, patch
from src.handshake import perform_handshake

def test_perform_handshake_accept():
    fake_sock = MagicMock()
    # server returns an ACCEPTED payload
    fake_sock.recv.return_value = b'{"TYPE":"ELECTION_ACK","STATUS":"ACCEPTED","MASTER_NAME":"MASTER_1"}'
    with patch('socket.create_connection', return_value=fake_sock):
        ok = perform_handshake('127.0.0.1', 6000, 'W-101', 'MASTER_1')
        assert ok is True
```

- [ ] **Step 2: Rodar teste (deve falhar)**

```bash
pytest tests/test_handshake.py -q
```

- [ ] **Step 3: Implementar código mínimo**

`src/handshake.py`:

```python
import socket
import json
from typing import Optional

def perform_handshake(master_ip: str, master_port: int, worker_uuid: str, master_name: str, timeout: float = 5.0) -> bool:
    s = socket.create_connection((master_ip, master_port), timeout)
    try:
        payload = json.dumps({"TYPE": "ELECTION_ACK", "WORKER_UUID": worker_uuid, "SELECTED_MASTER": master_name}).encode('utf-8')
        s.send(payload)
        resp = s.recv(4096)
        d = json.loads(resp.decode('utf-8'))
        return d.get('TYPE') == 'ELECTION_ACK' and d.get('STATUS') == 'ACCEPTED'
    finally:
        try:
            s.close()
        except Exception:
            pass
```

- [ ] **Step 4: Rodar testes e confirmar pass**

```bash
pytest tests/test_handshake.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/handshake.py tests/test_handshake.py
git commit -m "feat(handshake): add TCP handshake and tests"
```

### Self-review do Plano

1. Cada tarefa é pequena e testável (foco TDD). 
2. Não há placeholders: cada passo contém código e comandos exatos. 
3. Os arquivos a serem alterados estão listados; onde for preciso modificar `woker.py` ou `master.py`, os commits devem ser pequenos e documentados.

### Handoff / Execução

Opções de execução (escolha):
- **Subagent-Driven (recomendado)** — dispatch de subagent por tarefa.
- **Inline Execution** — eu executo as tarefas aqui usando `executing-plans` (requer sua aprovação).

Indique qual opção prefere e eu prosseguirei com a execução.
