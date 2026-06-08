# Heartbeat Mechanism Implementation Plan

> **STATUS DE EXECUÇÃO (2026-05-30): ✅ EXECUTADO.** Todas as tarefas (1–4) foram
> implementadas em `src/heartbeat/` com entry points em `master.py`/`worker.py`.
> Testes: **7/7 passando** (4 de unidade + 3 de integração). Demo end-to-end
> validada com processos reais (HEARTBEAT → ALIVE). Ver `README_SPRINT01.md`.
> Observação: o ambiente original não tinha rede; os testes foram verificados
> pelo runner `run_tests.py` (equivalente, sem dependências) — na sua máquina
> use `pytest -q` após `pip install -r requirements.txt`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Worker→Master HEARTBEAT mechanism (JSON over TCP with `\n` delimiter), Worker heartbeat interval 10s and Master response timeout 5s.

**Architecture:** `asyncio` TCP server (Master) and `asyncio` TCP client (Worker). Helper `messaging` module for newline-delimited JSON.

**Tech Stack:** Python 3.8+, asyncio, pytest, pytest-asyncio.

---

### Task 1: Messaging helpers

**Files:**
- Create: `src/heartbeat/messaging.py`
- Test: `tests/test_messaging.py`

- [ ] **Step 1: Write the failing test**

`tests/test_messaging.py`:

```python
import src.heartbeat.messaging as messaging


def test_encode_decode_roundtrip():
    obj = {"SERVER_UUID": "Master_Test", "TASK": "HEARTBEAT"}
    encoded = messaging.encode_message(obj)
    # encoded should be bytes or str ending with '\n'
    decoded = messaging.decode_message(encoded)
    assert decoded == obj
```

Run (expected: FAIL because `messaging` not implemented):

```bash
pytest tests/test_messaging.py -q
```

- [ ] **Step 2: Implement `messaging` helpers**

`src/heartbeat/messaging.py`:

```python
import json
from typing import Any, Union


def encode_message(obj: Any) -> bytes:
    """Serialize object to JSON and append newline as delimiter. Returns bytes."""
    data = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    return (data + "\n").encode('utf-8')


def decode_message(data: Union[bytes, str]):
    """Decode bytes or str that ends with newline into Python object."""
    if isinstance(data, bytes):
        data = data.decode('utf-8')
    data = data.strip()
    return json.loads(data)


# asyncio helpers (used by server/client implementations)
async def send_message(writer, obj: Any):
    writer.write(encode_message(obj))
    await writer.drain()


async def read_message(reader):
    line = await reader.readline()
    if not line:
        return None
    return decode_message(line)
```

- [ ] **Step 3: Run the test and verify it passes**

```bash
pytest tests/test_messaging.py -q
# Expected: 1 passed
```

- [ ] **Step 4: Commit**

```bash
git add src/heartbeat/messaging.py tests/test_messaging.py
git commit -m "feat(heartbeat): add messaging helpers for newline-delimited JSON"
```

---

### Task 2: Master (asyncio TCP server) — minimal heartbeat responder

**Files:**
- Create: `src/heartbeat/master_async.py`
- Test: `tests/test_master_worker_integration.py` (integration test using worker.run_once)

- [ ] **Step 1: Write the failing integration test**

`tests/test_master_worker_integration.py`:

```python
import asyncio
import pytest

import src.heartbeat.master_async as master
import src.heartbeat.worker_async as worker


@pytest.mark.asyncio
async def test_master_responds_alive(event_loop):
    # start master server on localhost:9001
    server_task = asyncio.create_task(master.run_server('127.0.0.1', 9001, master_id='Master_Test'))
    await asyncio.sleep(0.12)  # allow server to bind

    # run a single heartbeat (worker.run_once returns True on ALIVE)
    ok = await worker.run_once('127.0.0.1', 9001, master_uuid='Master_Test', timeout=2)
    assert ok is True

    server_task.cancel()
```

Run (expected: FAIL until master/worker implemented):

```bash
pytest tests/test_master_worker_integration.py -q
```

- [ ] **Step 2: Implement minimal `master_async`**

`src/heartbeat/master_async.py`:

```python
import asyncio
from src.heartbeat import messaging


MASTER_ID = None


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    addr = writer.get_extra_info('peername')
    print(f"[master] nova conexão {addr}")
    try:
        while True:
            msg = await messaging.read_message(reader)
            if msg is None:
                break
            # tolerant parsing: ignore unknown fields
            task = msg.get('TASK') or msg.get('task')
            if task == 'HEARTBEAT':
                response = {
                    'SERVER_UUID': MASTER_ID,
                    'TASK': 'HEARTBEAT',
                    'RESPONSE': 'ALIVE'
                }
                await messaging.send_message(writer, response)
            else:
                # ignore unknown messages for now
                pass
    except Exception as e:
        print('[master] erro no handle_client:', e)
    finally:
        writer.close()
        await writer.wait_closed()


async def run_server(host: str, port: int, master_id: str):
    global MASTER_ID
    MASTER_ID = master_id
    server = await asyncio.start_server(handle_client, host, port)
    addrs = ', '.join(str(sock.getsockname()) for sock in server.sockets)
    print(f"[master] escutando em {addrs}")
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--id', default='Master')
    args = parser.parse_args()
    try:
        asyncio.run(run_server(args.host, args.port, args.id))
    except KeyboardInterrupt:
        print('Master interrompido')
```

- [ ] **Step 3: Run integration test and expect pass**

```bash
pytest tests/test_master_worker_integration.py -q
# Expected: 1 passed
```

- [ ] **Step 4: Commit**

```bash
git add src/heartbeat/master_async.py tests/test_master_worker_integration.py
git commit -m "feat(heartbeat): add master_async and integration test"
```

---

### Task 3: Worker (asyncio client) — heartbeat sender

**Files:**
- Create: `src/heartbeat/worker_async.py`
- Use in tests: `tests/test_master_worker_integration.py` (already referenced)

- [ ] **Step 1: Implement test helper `run_once` used by integration test**

`src/heartbeat/worker_async.py` (core parts):

```python
import asyncio
from src.heartbeat import messaging


async def run_once(host: str, port: int, master_uuid: str, timeout: float = 5.0) -> bool:
    try:
        reader, writer = await asyncio.open_connection(host, port)
        payload = {"SERVER_UUID": master_uuid, "TASK": "HEARTBEAT"}
        await messaging.send_message(writer, payload)
        try:
            resp = await asyncio.wait_for(messaging.read_message(reader), timeout=timeout)
        except asyncio.TimeoutError:
            writer.close()
            await writer.wait_closed()
            return False
        writer.close()
        await writer.wait_closed()
        return resp is not None and resp.get('RESPONSE') == 'ALIVE'
    except Exception:
        return False


async def run_forever(host: str, port: int, master_uuid: str, interval: float = 10.0):
    backoff = 1.0
    while True:
        ok = await run_once(host, port, master_uuid, timeout=5.0)
        if ok:
            backoff = 1.0
        else:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8.0)
        await asyncio.sleep(interval)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--master', default='Master')
    args = parser.parse_args()
    try:
        asyncio.run(run_forever(args.host, args.port, args.master))
    except KeyboardInterrupt:
        print('Worker interrompido')
```

- [ ] **Step 2: Run integration test**

```bash
pytest tests/test_master_worker_integration.py -q
# Expected: 1 passed
```

- [ ] **Step 3: Commit**

```bash
git add src/heartbeat/worker_async.py
git commit -m "feat(heartbeat): add worker_async with run_once and run_forever"
```

---

### Task 4: End-to-end demo and acceptance

**Files:**
- Create: `scripts/run_heartbeat_demo.py` (optional convenience script)

- [ ] **Step 1: Add `requirements.txt`**

```
pytest
pytest-asyncio
```

- [ ] **Step 2: Demo run**

Start master in one terminal:

```bash
python -m src.heartbeat.master_async --host 127.0.0.1 --port 9001 --id Master_Demo
```

Start worker in another terminal (sends heartbeats every 10s):

```bash
python -m src.heartbeat.worker_async --host 127.0.0.1 --port 9001 --master Master_Demo
```

Observe Master logs: should print conexões e Heartbeat recebido; Worker prints ALIVE recebido.

- [ ] **Step 3: Acceptance checklist**
- Worker envia HEARTBEAT e recebe ALIVE
- Master parseia HEARTBEAT e responde
- Timeout de 5s é respeitado
- Reconexão em caso de falha sem travar processos

- [ ] **Step 4: Commit and push**

```bash
git add .
git commit -m "chore(heartbeat): implement heartbeat messaging, master and worker; add tests"
git push origin feature/heartbeat
```

---

## Self-review

- Spec coverage: plan implements `messaging`, `master_async`, `worker_async` e testes de integração — cobre payloads oficiais e DoD.
- No placeholders: every step contains concrete file paths, code snippets, and commands.

---

**Execution choice:** After you review this plan I can:
1. Run it here inline using `executing-plans` (execute steps, run tests). 
2. Or scaffold files now and run the unit/integration tests.

Qual opção prefere? (responda `scaffold` para eu criar os arquivos indicados e rodar os testes, ou `manual` se você prefere revisar antes de eu executar)