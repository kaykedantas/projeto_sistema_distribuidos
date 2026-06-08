# Sprint 3.1 — Correções de Integração dos Arquivos Unificados — Implementation Plan

> **STATUS DE EXECUÇÃO (2026-06-02): ✅ EXECUTADO.**
> Arquivos `master.py` e `worker.py` na raiz corrigidos.
> 5 bugs resolvidos: porta UDP, histerese, set_load automático, idle_workers e
> canal command_redirect/release integrado ao work_loop.

> **Escopo:** somente `master.py` e `worker.py` na raiz do projeto.
> As pastas `sprints/` NÃO são alteradas.

**Goal:** Corrigir os 5 bugs identificados na inspeção dos arquivos consolidados para
que o sistema funcione em sala de aula (duas máquinas na mesma LAN) sem configuração
manual adicional além das portas.

**Architecture:** asyncio single-thread. Estado compartilhado protegido pela ausência de
`await` nas seções críticas (Nota 38). Dois novos dicts `pending_redirects` /
`pending_releases` no Master para entregar comandos M2M na próxima apresentação do Worker.

---

### Task 1 — Bug 1: Porta UDP de descoberta divergente

**Arquivo:** `worker.py`

- [x] **Step 1:** Alterar `DEFAULT_DISC_PORT = 5001` → `DEFAULT_DISC_PORT = 5000`
  para que o worker envie `DISCOVERY` para a mesma porta em que o master escuta.

**Por quê:** O worker usa `DEFAULT_DISC_PORT` como destino do pacote UDP. O master
escuta em `DEFAULT_DISC_PORT = 5000`. Com portas divergentes, o `DISCOVERY` nunca
chega ao master e o worker fica em loop de `NO_MASTER_FOUND`.

---

### Task 2 — Bug 2: Histerese de carga com valores invertidos

**Arquivo:** `master.py`

- [x] **Step 1:** Alterar `DEFAULT_CAPACITY = 1` → `DEFAULT_CAPACITY = 100`
- [x] **Step 2:** Alterar `DEFAULT_RELEASE_THRESHOLD = 10` → `DEFAULT_RELEASE_THRESHOLD = 60`

**Por quê:** O PDF (Nota 35) exige `release_threshold < capacity` para criar a "zona
morta" entre saturação e liberação. Com capacity=1 e release_threshold=10, qualquer
carga < 10 dispara liberação imediatamente após saturação — o efeito ping-pong que a
histerese deveria evitar.

---

### Task 3 — Bug 3: `set_load()` nunca chamado internamente

**Arquivo:** `master.py`

- [x] **Step 1:** No `__init__`, após `self.tasks = deque(tasks or [])`, adicionar:
  ```python
  if self.tasks:
      self.current_load = len(self.tasks)
  ```
  (Não chamar `set_load` no `__init__` porque o event loop ainda não está rodando e
  os callbacks `on_saturation`/`on_release` não estão configurados neste ponto.)

- [x] **Step 2:** Em `_handle_apresentacao`, após `self.tasks.popleft()`, adicionar:
  ```python
  self.set_load(len(self.tasks))
  ```

**Por quê:** `set_load` é o único ponto que dispara `on_saturation`/`on_release`. Sem
chamá-lo, a carga fica em 0 eternamente e a negociação M2M nunca inicia. A chamada
após `popleft` é atômica (sem `await` no meio) e reflete a carga real após servir a
tarefa ao Worker.

---

### Task 4 — Bug 4: `idle_workers` nunca populado

**Arquivo:** `master.py`

- [x] **Step 1:** Em `_handle_apresentacao`, no branch `else` (fila vazia), antes de
  enviar `NO_TASK`:
  ```python
  if not emprestado and all(w.get("id") != uuid_ for w in self.idle_workers):
      self.idle_workers.append({"id": uuid_, "address": f"{addr[0]}:{addr[1]}"})
      logger.info("Worker %s adicionado aos ociosos (total: %d)", uuid_, len(self.idle_workers))
  ```

**Por quê:** O fluxo de negociação M2M (Sprint 3) requer que o master B tenha workers
em `idle_workers` para poder oferecer a outros masters. Um worker que apresenta com
fila vazia está de fato ocioso e disponível. Workers emprestados (`SERVER_UUID`
presente) não são adicionados — não faz sentido reemprestar um worker já emprestado.

---

### Task 5 — Bug 5: Sem canal para command_redirect / command_release

**Arquivos:** `master.py` e `worker.py`

#### 5a: Master — filas de comandos pendentes

- [x] **Step 1:** No `__init__`, adicionar:
  ```python
  self.pending_redirects = {}   # worker_id -> new_master_address
  self.pending_releases  = {}   # worker_id -> original_master_address
  ```

- [x] **Step 2:** Em `_handle_apresentacao`, no início (antes de verificar a fila),
  inserir a lógica de comandos pendentes:
  ```python
  # command_release tem prioridade: devolve worker ao master de origem
  if uuid_ in self.pending_releases:
      orig = self.pending_releases.pop(uuid_)
      self.borrowed_in.pop(uuid_, None)
      await send_message(writer, m2m_command_release(orig))
      logger.info("command_release -> Worker %s (origem %s)", uuid_, orig)
      return
  # command_redirect: redireciona worker ocioso para outro master
  if uuid_ in self.pending_redirects:
      new_addr = self.pending_redirects.pop(uuid_)
      self.idle_workers = [w for w in self.idle_workers if w.get("id") != uuid_]
      await send_message(writer, m2m_command_redirect(new_addr))
      logger.info("command_redirect -> Worker %s -> %s", uuid_, new_addr)
      return
  ```

- [x] **Step 3:** Reescrever `_redirect_workers` para usar `pending_redirects`:
  ```python
  async def _redirect_workers(self, worker_details, new_master_address) -> None:
      for w in worker_details:
          wid = w.get("id")
          self.pending_redirects[wid] = new_master_address
          logger.info("Redirecionamento pendente: Worker %s -> %s", wid, new_master_address)
  ```
  O parâmetro passa a ser a string `"ip:porta"` do master solicitante (extraída do
  payload de `request_help`), não mais o peername da conexão (que teria porta efêmera).

- [x] **Step 4:** Em `_handle_m2m`, no tratamento de `request_help`, extrair o endereço
  do master solicitante do payload:
  ```python
  requester_addr = msg.get("payload", {}).get("master_address",
                    f"{addr[0]}:{self.port}")  # fallback: IP do peer + porta deste master
  await self._redirect_workers(ofertados, requester_addr)
  ```

- [x] **Step 5:** Adicionar método `_notify_origin_returned`:
  ```python
  async def _notify_origin_returned(self, worker_id, origem_addr):
      try:
          host, _, port_s = str(origem_addr).rpartition(":")
          reader, writer = await asyncio.wait_for(
              asyncio.open_connection(host, int(port_s)), timeout=5.0)
          await send_message(writer, m2m_notify_worker_returned(worker_id))
          writer.close()
          with contextlib.suppress(Exception): await writer.wait_closed()
          logger.info("notify_worker_returned -> %s (worker %s)", origem_addr, worker_id)
      except (asyncio.TimeoutError, OSError) as e:
          logger.warning("notify_worker_returned a %s falhou (%s)", origem_addr, e)
  ```

- [x] **Step 6:** Adicionar função `_setup_auto_callbacks` e chamá-la em `run_server`:
  ```python
  def _setup_auto_callbacks(m: Master) -> None:
      def _on_saturation(needed):
          for nid in list(m.neighbors):
              asyncio.get_event_loop().create_task(m.request_help_to(nid, needed))
      def _on_release():
          loop = asyncio.get_event_loop()
          for wid, info in list(m.borrowed_in.items()):
              orig = info.get("origem")
              m.pending_releases[wid] = orig
              if orig:
                  loop.create_task(m._notify_origin_returned(wid, orig))
      m.on_saturation = _on_saturation
      m.on_release    = _on_release
  ```

#### 5b: m2m_request_help — incluir endereço do master solicitante

- [x] **Step 7:** Atualizar `m2m_request_help` para aceitar e incluir `master_address`:
  ```python
  def m2m_request_help(master_id, current_load, capacity, workers_needed,
                       master_address=None, request_id=None):
      payload = {"master_id": master_id, "current_load": current_load,
                 "capacity": capacity, "workers_needed": workers_needed}
      if master_address:
          payload["master_address"] = master_address
      return make_m2m_message("request_help", payload, request_id)
  ```

- [x] **Step 8:** Em `request_help_to`, passar o endereço real do master:
  ```python
  master_addr = f"{detect_outbound_ip()}:{self.port}"
  msg = m2m_request_help(self.master_id, self.current_load, self.capacity,
                         workers_needed, master_address=master_addr)
  ```

#### 5c: Worker — integrar redirect/release ao work_loop

- [x] **Step 9:** Alterar `do_one_task` para retornar uma 4-tupla
  `(code, host, port, origin)` e tratar `command_redirect`/`command_release`:
  ```python
  # Após receber resp:
  msg_type = resp.get("type") if isinstance(resp, dict) else None
  if msg_type == "command_redirect":
      new_addr = resp.get("payload", {}).get("new_master_address", "")
      new_host, new_port = parse_address(new_addr)
      cur_origin = origin_master or f"{host}:{port}"
      await register_as_temporary(new_host, new_port, worker_uuid, cur_origin)
      return "REDIRECTED", new_host, new_port, cur_origin
  if msg_type == "command_release":
      orig = resp.get("payload", {}).get("original_master_address", "")
      oh, op = parse_address(orig)
      return "RELEASED", oh, op, None
  ```
  Tipos já tratados retornam: `("NO_TASK", host, port, origin_master)`,
  `(status, host, port, origin_master)`, `(None, host, port, origin_master)`.

- [x] **Step 10:** Alterar `work_loop` para manter e atualizar o estado de conexão:
  ```python
  async def work_loop(host, port, worker_uuid, origin_master=None, interval=2.0):
      backoff = 1.0
      cur_host, cur_port, cur_origin = host, port, origin_master
      while True:
          try:
              res, cur_host, cur_port, cur_origin = await do_one_task(
                  cur_host, cur_port, worker_uuid, cur_origin)
              backoff = 1.0
              if res == "NO_TASK":
                  await asyncio.sleep(interval)
              elif res in ("REDIRECTED", "RELEASED"):
                  await asyncio.sleep(0.5)
              else:
                  await asyncio.sleep(0.1)
          except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as exc:
              logger.warning("Falha (%s); reconectando em %.0fs", exc, backoff)
              await asyncio.sleep(backoff)
              backoff = min(backoff * 2, BACKOFF_MAX)
  ```

---

## Self-review

- **Bug 1 (porta):** corrigido em 1 linha. Imediato e sem risco.
- **Bug 2 (histerese):** corrigido em 2 linhas. Valores do PDF restaurados.
- **Bug 3 (set_load):** chamada adicionada em 1 ponto cirúrgico (pós-popleft).
- **Bug 4 (idle_workers):** 3 linhas adicionadas no branch NO_TASK existente.
- **Bug 5 (canal M2M):** maior intervenção, mas contida em dois arquivos sem
  tocar nas Sprints 01/02/2.1 (heartbeat, tasks, discovery permanecem intactos).
- **Retro-compatibilidade:** `--mode heartbeat` e `--mode tasks` não passam por
  `pending_redirects`/`pending_releases` (só são checados em `_handle_apresentacao`).
  O heartbeat usa `_handle_heartbeat`, não `_handle_apresentacao`. Sem impacto.
- **Compatibilidade de protocolo:** `master_address` no payload de `request_help` é
  um campo extra; implementações que não o reconhecem simplesmente ignoram (Nota 31).

## Como testar em sala de aula após as correções

```bash
# --- Máquina A (Master com tarefas) ---
python master.py --port 7011 --disc-port 5000 --id MASTER_A --name MASTER_A \
  --tasks t1,t2,t3,t4,t5 --capacity 3 --release-threshold 1

# --- Máquina B (Master vizinho com workers) ---
python master.py --port 7011 --disc-port 5000 --id MASTER_B --name MASTER_B \
  --tasks "" --capacity 100 \
  --neighbors "MASTER_A@<IP_MAQUINA_A>:7011"

# --- Máquina B também (ou C) — Worker ---
python worker.py --uuid W-1 --disc-port 5000
# (descobre ambos, elege MASTER_A por menor nome, começa a trabalhar)
```

Sprint 01 (heartbeat fixo):
```bash
python master.py --port 7011 --disc-port 0
python worker.py --mode heartbeat --host <IP_MASTER> --port 7011 --master MASTER_A
```

Sprint 02 (tarefas fixo):
```bash
python master.py --port 7011 --disc-port 0 --tasks Ana,Pedro,Carlos
python worker.py --mode tasks --host <IP_MASTER> --port 7011 --uuid W-1
```
