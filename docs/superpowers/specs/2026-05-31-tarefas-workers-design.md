# Sprint 2 — Comunicação de Tarefas e Apresentação de Workers — Design

Date: 2026-05-31
Depende de: Sprint 01 (Heartbeat) — reaproveita `messaging` e mantém o `HEARTBEAT`.

## Resumo

- **Objetivo:** implementar o ciclo de vida completo de uma tarefa — desde a
  apresentação do Worker (identificando sua origem), passando pela distribuição
  de uma tarefa pelo Master, o processamento no Worker e o reporte de status,
  até a confirmação final (ACK) do Master.
- **Decisão estrutural (aprovada):** organização por **pastas de sprint**. O
  código vive em `sprints/sprint02_tarefas/`, que é um retrato **cumulativo**
  (contém a lógica da Sprint 01 + as adições da Sprint 02) e roda de forma
  independente. A Sprint 01 permanece preservada em `sprints/sprint01_heartbeat/`.
- **Abordagem de ciclo (aprovada — "A"):** conexão TCP persistente + Master com
  estado em memória (fila de tarefas + registro de workers). O Worker roda um
  loop contínuo de trabalho. Reconecta em falha/timeout.

## Requisitos funcionais (extraídos do `plano_proj_SD-26_1.pdf`)

- **Tarefa 01 — Apresentação e Identificação (Worker → Master):** o Worker se
  apresenta enviando seu `WORKER_UUID`; se for "emprestado", inclui também o
  `SERVER_UUID` do seu Master de origem.
- **Tarefa 02 — Distribuição de Carga e Fila (Master → Worker):** o Master
  gerencia uma fila de tarefas pendentes; ao receber uma apresentação, entrega
  uma tarefa (`QUERY`) se houver, ou informa `NO_TASK` se a fila estiver vazia.
- **Tarefa 03 — Processamento e Reporte de Status (Worker → Master):** ao
  receber `QUERY`, o Worker simula processamento (sleep/cálculo) e reporta o
  resultado com `STATUS` `OK` ou `NOK`.
- **Tarefa 04 — Confirmação (ACK) e Persistência (Master → Worker):** o Master
  recebe o status, responde `ACK` imediatamente (liberando o Worker) e registra
  em log qual Worker (local ou emprestado) concluiu qual tarefa.

## Payloads oficiais (exatos do PDF — "Definição do Payload Padrão")

Todas as mensagens terminam com `\n` e os valores de controle são CAIXA ALTA.

**2.1 / 2.1b — Solicitação de Tarefa (Worker → Master)**
Obrigatórios: `WORKER`, `WORKER_UUID`. Opcional: `SERVER_UUID` (só se emprestado).

```json
{ "WORKER": "ALIVE", "WORKER_UUID": "W-123" }
```
```json
{ "WORKER": "ALIVE", "WORKER_UUID": "W-999", "SERVER_UUID": "Master-B" }
```

**2.2 / 2.3 — Entrega de Tarefa (Master → Worker)**

```json
{ "TASK": "QUERY", "USER": "Michel" }
```
```json
{ "TASK": "NO_TASK" }
```

**2.4 — Reporte de Status (Worker → Master)**
Obrigatórios: `STATUS` ("OK"|"NOK"), `TASK`, `WORKER_UUID`.

```json
{ "STATUS": "OK", "TASK": "QUERY", "WORKER_UUID": "W-123" }
```

**2.5 — Confirmação Final (Master → Worker)**
Campo de controle: `STATUS` fixo "ACK"; inclui `WORKER_UUID` para correlação.

```json
{ "STATUS": "ACK", "WORKER_UUID": "W-123" }
```

## Arquitetura proposta

Pacote estendido em `sprints/sprint02_tarefas/src/heartbeat/`:

- **`messaging.py`** — reaproveitado integralmente da Sprint 01 (encode/decode +
  helpers assíncronos `send_message`/`read_message`, JSON delimitado por `\n`).
- **`master_async.py`** — Master assíncrono, agora com:
  - `tasks: deque` — fila de tarefas pendentes (cada tarefa = nome de `USER`).
  - `workers: dict` — registro de workers conhecidos (uuid → {origem local/
    emprestado, master de origem, tarefas concluídas}).
  - Tratamento por tipo de mensagem na mesma conexão:
    - `HEARTBEAT` → responde `ALIVE` (mantido da Sprint 01).
    - `WORKER: ALIVE` → registra/atualiza o worker; se há tarefa na fila,
      desenfileira e responde `QUERY`+`USER`; senão responde `NO_TASK`.
    - `STATUS` (OK/NOK) → loga o resultado associando worker↔tarefa↔origem e
      responde `ACK`.
- **`worker_async.py`** — Worker assíncrono, agora com loop de trabalho:
  - `present()` — envia `WORKER: ALIVE` + `WORKER_UUID` (+ `SERVER_UUID` se
    emprestado).
  - `process_task(user)` — "executor": simula trabalho (sleep curto/cálculo) e
    devolve `OK`/`NOK`. Determinístico-injetável para testes.
  - `work_loop()` — present → recebe QUERY/NO_TASK → (se QUERY) processa →
    reporta STATUS → aguarda ACK → repete; em `NO_TASK` espera curto e
    reapresenta; em timeout (5s)/erro reconecta com backoff.
- **Entrypoints** `master.py` / `worker.py` na raiz da pasta da sprint.

### Concorrência (por que sem locks)

O event loop do asyncio é single-thread: duas corrotinas só alternam em pontos
de `await`. As operações sobre a fila (`popleft`) e o registro (`dict`) são
feitas **sem `await` no meio**, portanto são atômicas em relação a outras
corrotinas. Isso dispensa locks e mantém o código simples. (Se no futuro a
fila for alimentada por outra thread — ex.: simulação de carga da Sprint 03 —
revê-se este ponto.)

## Fluxo de dados (1 ciclo)

```
Worker → Master : {"WORKER":"ALIVE","WORKER_UUID":"W-123"[,"SERVER_UUID":"Master-B"]}
Master → Worker : {"TASK":"QUERY","USER":"Michel"}        (ou {"TASK":"NO_TASK"})
        [Worker processa → decide OK/NOK]
Worker → Master : {"STATUS":"OK","TASK":"QUERY","WORKER_UUID":"W-123"}
Master → Worker : {"STATUS":"ACK","WORKER_UUID":"W-123"}
        [repete]
```

## Erros, resiliência e robustez

- **Strict parsing:** campos desconhecidos são ignorados; ausência de campo
  obrigatório (`WORKER`/`WORKER_UUID` na apresentação; `STATUS`/`TASK`/
  `WORKER_UUID` no reporte) é logada e a mensagem é descartada sem derrubar o
  Master.
- **Case sensitivity:** `ALIVE`, `QUERY`, `NO_TASK`, `OK`, `NOK`, `ACK` sempre
  em CAIXA ALTA.
- **Timeout:** o Worker aguarda a resposta do Master por no máximo 5s; ao
  estourar, considera a conexão perdida e reconecta (backoff exponencial curto).
- **NO_TASK:** o Worker aguarda um curto intervalo e reapresenta (poll).
- **Worker emprestado:** presença de `SERVER_UUID` é tratada (DoD item 5); o
  Master apenas registra/loga como "emprestado" — a lógica completa de
  empréstimo é da Sprint 03.

## Seeding de tarefas (para teste e demo)

Nesta sprint ainda não há cliente real gerando carga (isso evolui na Sprint 03).
Para tornar o fluxo testável e demonstrável, o Master aceita uma lista inicial
de tarefas via CLI:

```
python master.py --tasks Michel,Julia
```

Default: `Michel,Julia` (casa com os casos de sala CT01 e CT02).

## Testes e DoD (critérios de aceite)

**Unidade**
- Roundtrip dos novos payloads no `messaging`.
- `process_task` retorna OK/NOK conforme injeção determinística.

**Integração (sockets TCP reais) — casos de sala:**
- **CT01** Worker local: `{"WORKER":"ALIVE","WORKER_UUID":"W-123"}` → recebe
  `{"TASK":"QUERY","USER":...}`.
- **CT02** Worker emprestado: `{...,"SERVER_UUID":"Master-B"}` → recebe `QUERY`;
  Master loga como emprestado.
- **CT03** Fila vazia: apresentação com fila vazia → `{"TASK":"NO_TASK"}`.
- **CT04** Reporte OK: `{"STATUS":"OK",...}` → `{"STATUS":"ACK",...}`.
- **CT05** Reporte NOK: `{"STATUS":"NOK",...}` → `{"STATUS":"ACK",...}` (Master
  registra a falha mas confirma o recebimento).
- **Ciclo completo** end-to-end: present → QUERY → OK → ACK.

**DoD (do PDF):**
1. Worker faz o handshake de apresentação (envia UUID).
2. Master distribui uma tarefa real da fila OU informa corretamente `NO_TASK`.
3. Worker processa e o Master recebe `OK`/`NOK`.
4. Worker recebe o `ACK` final, fechando o ciclo sem erros de parsing/perda no
   stream TCP.
5. Sistema trata corretamente presença/ausência do campo `SERVER_UUID`.

## Ponto de atenção — divergência no próprio PDF (campo do ACK)

O PDF é internamente inconsistente quanto ao payload do ACK:
- Backlog (Tarefa 04, 2.5) e tabela de casos de sala (CT04/CT05) mostram o ACK
  **sem** o uuid: `{"STATUS":"ACK"}`.
- A seção "Definição do Payload Padrão" (autoritativa, diz que "todos os pacotes
  devem seguir rigorosamente esta estrutura") mostra o ACK **com** o uuid:
  `{"STATUS":"ACK","WORKER_UUID":"string"}`.

**Decisão adotada:** o Master **envia** `{"STATUS":"ACK","WORKER_UUID":"..."}`
(segue a seção autoritativa e ajuda na correlação), e o Worker **aceita** o ACK
com ou sem o campo extra (interoperabilidade — strict parsing ignora campos
desconhecidos e não exige o uuid para reconhecer o ACK). Se o avaliador exigir
o ACK literalmente "pelado" (`{"STATUS":"ACK"}`), basta um ajuste de uma linha.

## Decisões e observações

- Mantém asyncio (padrão da Sprint 01); nada de threads.
- Reaproveita `messaging.py` sem alteração.
- O `HEARTBEAT` da Sprint 01 continua atendido pelo Master no mesmo socket.
- Pasta da sprint é cumulativa e auto-contida (roda isolada).

## Referências

- `plano_proj_SD-26_1.pdf` — seções "Sprint 2", "Definição do Payload Padrão",
  "Notas de Implementação" e tabela de Casos de Teste (CT01–CT05).
- Spec da Sprint 01: `docs/superpowers/specs/2026-05-30-heartbeat-design.md`.
