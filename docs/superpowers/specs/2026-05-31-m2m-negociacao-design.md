# Sprint 3 — Protocolo de Negociação Master-to-Master e Redirecionamento Dinâmico de Workers — Design

Date: 2026-05-31
Depende de: Sprint 01 (Heartbeat), Sprint 02 (Tarefas, incluindo `SERVER_UUID`
para emprestados) e Sprint 2.1 (Descoberta/Eleição — presente no código,
cumulativa, mas não acionada por este fluxo). Reaproveita `messaging` e o ciclo
de tarefas.

## Resumo

- **Objetivo:** implementar a camada de comunicação **P2P entre Masters**,
  permitindo que um Master saturado negocie e receba, de forma autônoma e
  consensual, Workers emprestados de um Master vizinho. Cobre o ciclo completo:
  pedido de ajuda, análise/resposta, redirecionamento, registro temporário do
  Worker e devolução quando a carga normaliza.
- **Decisão estrutural (aprovada):** pasta cumulativa `sprints/sprint03_negociacao/`
  (cópia da `sprint02_1_discovery` + camada de negociação). Roda isolada.
- **Concorrência (aprovada):** **AsyncIO** (mantém o padrão do projeto; sem
  misturar threads). Estado compartilhado protegido pelo modelo single-thread do
  event loop (operações críticas sem `await` no meio).
- **Acionamento de carga (aprovado):** **programático** via `set_load(n)` +
  thresholds configuráveis. `capacity=100` (saturação) e `release_threshold=60`
  (liberação, 60% → histerese), conforme exemplos do PDF.

> **Nota sobre "eleição".** Esta sprint NÃO tem eleição de líder. Masters são
> peers iguais; o "consenso" do objetivo O4 significa apenas que os dois Masters
> concordam sobre o empréstimo (um pede, o outro aceita). A eleição Worker→Master
> é assunto da Sprint 2.1 e permanece intacta no código, sem ser acionada aqui.

## Pré-requisitos (do PDF)

- Sprint 01 (Heartbeat) e Sprint 02 (ciclo de tarefas com `SERVER_UUID`) OK.
- Cada Master possui `master_id` único e endereço (`ip:porta`) **conhecido pelos
  vizinhos** — ou seja, a topologia M2M usa um **diretório de vizinhos
  configurado** (estático), não a descoberta UDP da Sprint 2.1.

## Estrutura padrão da mensagem M2M (do PDF)

Toda comunicação Master-to-Master segue este envelope, terminado por `\n`:

```json
{
  "type": "TIPO_DA_MENSAGEM",
  "request_id": "uuid_v4_para_rastreio",
  "payload": { }
}
```

- `type` substitui a "URL da API" e identifica a operação (sempre em minúsculas).
- `request_id` é um UUID v4 que correlaciona requisição e resposta, mesmo em
  conexões concorrentes.

## Os 7 tipos de mensagem (payloads exatos do PDF)

**1. request_help — Master A → Master B** (carga > threshold)
```json
{ "type": "request_help", "request_id": "<uuid>",
  "payload": { "master_id": "A", "current_load": 150, "capacity": 100, "workers_needed": 2 } }
```

**2a. response_accepted — Master B → Master A** (mesmo request_id)
```json
{ "type": "response_accepted", "request_id": "<uuid>",
  "payload": { "workers_offered": 2,
    "worker_details": [ { "id": "B1", "address": "ip:port_b1" }, { "id": "B2", "address": "ip:port_b2" } ] } }
```

**2b. response_rejected — Master B → Master A** (mesmo request_id)
```json
{ "type": "response_rejected", "request_id": "<uuid>", "payload": { "reason": "high_load" } }
```
Valores de `reason`: `high_load`, `no_workers_available`, `refused`.

**3. command_redirect — Master B → Worker B1** (request_id próprio, fluxo M↔W)
```json
{ "type": "command_redirect", "request_id": "<uuid>",
  "payload": { "new_master_address": "ip_master_A:port" } }
```

**4. register_temporary_worker — Worker B1 → Master A** (request_id próprio)
```json
{ "type": "register_temporary_worker", "request_id": "<uuid>",
  "payload": { "worker_id": "B1", "original_master_address": "ip_master_B:port" } }
```

**5. command_release — Master A → Worker B1** (carga normalizou)
```json
{ "type": "command_release", "request_id": "<uuid>",
  "payload": { "original_master_address": "ip_master_B:port" } }
```

**6. notify_worker_returned — Master A → Master B** (após command_release)
```json
{ "type": "notify_worker_returned", "request_id": "<uuid>", "payload": { "worker_id": "B1" } }
```

## Arquitetura proposta

Pacote estendido em `sprints/sprint03_negociacao/src/heartbeat/`:

- **`messaging.py`** — reaproveitado (JSON + `\n`).
- **`m2m.py`** — NOVO. Envelope e construtores:
  - `new_request_id()` → UUID v4 (`str`).
  - `make_message(type, payload, request_id=None)` → dict no envelope padrão
    (gera `request_id` se ausente).
  - Construtores tipados: `request_help(...)`, `response_accepted(...)`,
    `response_rejected(reason, request_id)`, `command_redirect(...)`,
    `register_temporary_worker(...)`, `command_release(...)`,
    `notify_worker_returned(...)`.
  - `REASONS = {"high_load", "no_workers_available", "refused"}`.
- **`master_async.py`** — Master passa a ser **peer P2P**, com:
  - `neighbors: dict[str, tuple[str,int]]` — diretório de Masters vizinhos.
  - Estado de carga: `current_load`, `capacity=100`, `release_threshold=60`;
    método `set_load(n)` que dispara negociação (subida) / devolução (descida).
  - Conjunto de Workers ociosos disponíveis para empréstimo e registro de
    `borrowed_in` (recebidos) / `lent_out` (cedidos), com contadores no log.
  - `pending: dict[str, asyncio.Future]` — correlação `request_id`→resposta,
    com timeout de 5s.
  - Pool de conexões M2M reutilizável: `m2m_conns: dict[str, (reader,writer)]`.
  - Handlers no dispatch TCP (somados aos anteriores): `request_help`,
    `response_accepted`/`response_rejected` (resolvem a Future via `request_id`),
    `register_temporary_worker`, `notify_worker_returned`. `type` desconhecido →
    loga e ignora (CT09).
  - Métodos de negociação: `request_help_to(neighbor, workers_needed)`,
    `evaluate_help_request(payload)` → accepted/rejected, `redirect_workers(...)`,
    `release_worker(worker_id)`.
- **`worker_async.py`** — trata comandos do Master:
  - `command_redirect` → encerra graciosamente (sem perder tarefa em execução),
    conecta ao `new_master_address`, envia `register_temporary_worker` e opera
    pelo ciclo da Sprint 02 com `SERVER_UUID` = Master de origem.
  - `command_release` → reconecta ao `original_master_address` (apresentação
    Sprint 02).
- **Entrypoints** `master.py` (novos args: `--neighbors id@ip:porta,...`,
  `--capacity`, `--release-threshold`) e `worker.py` (trata os comandos acima).

### Concorrência (por que AsyncIO basta)

Um Master precisa, ao mesmo tempo: atender Workers locais, Workers emprestados,
conexões com Masters vizinhos e a simulação de carga. Com asyncio, tudo são
corrotinas no mesmo loop; as estruturas compartilhadas (fila de tarefas,
conjuntos de Workers, registro de emprestados, `pending`) são acessadas em
trechos sem `await` no meio, o que as torna atômicas entre corrotinas e dispensa
locks. A Nota 38 do PDF exige proteção contra corrida; com single-thread isso é
garantido pela ausência de preempção entre `await`s.

## Fluxo completo (diagrama do PDF)

```
Master A (load > capacity)
  A → B : request_help {master_id, current_load, capacity, workers_needed}
  B → A : response_accepted {workers_offered, worker_details[]}   | response_rejected {reason}
  B → W : command_redirect {new_master_address}     (para cada worker ofertado)
  [W encerra graciosamente a conexão com B]
  W → A : (nova conexão) register_temporary_worker {worker_id, original_master_address}
  [W opera sob A — Sprint 02 com SERVER_UUID]
Master A (load < release_threshold)
  A → W : command_release {original_master_address}
  A → B : notify_worker_returned {worker_id}
  [W reconecta a B — apresentação Sprint 02]
```

## Erros, resiliência e observabilidade

- **Strict parsing (Nota 31):** campos extras ignorados; obrigatório ausente →
  falha com log, sem derrubar o processo.
- **Case sensitivity (Nota 32):** todos os `type` em minúsculas, exatamente como
  definidos.
- **request_id (Nota 33):** UUID v4 por requisição; a resposta a um `request_help`
  reusa o mesmo; `command_redirect`/`register_temporary_worker`/`command_release`/
  `notify_worker_returned` são fluxos próprios com `request_id` independente.
- **Timeout (Nota 34, CT07):** solicitante aguarda ≤ 5s; após isso libera o
  `request_id`, loga e tenta o próximo vizinho (ou aborta).
- **Histerese (Nota 35):** `release_threshold < capacity` evita empréstimo e
  devolução imediatos do mesmo Worker (ping-pong).
- **Queda do receptor (CT08):** Worker emprestado detecta a queda do Master A e
  tenta voltar ao Master B; estado consistente restaurado.
- **type desconhecido (CT09):** loga e ignora.
- **Logs (Tarefa 07):** toda emissão/recebimento M2M com `request_id`, `type` e
  timestamp; contadores de Workers locais vs. emprestados a cada mudança; ciclo
  de vida completo de cada Worker emprestado.

## Testes e DoD (critérios de aceite)

**Unidade (`m2m.py`):** envelope correto; `request_id` é UUID v4; construtores
geram os payloads exatos; `reason` válido.

**Integração (sockets reais em loopback), mapeando os CT:**
- **CT01** help aceito: A→B `request_help` (workers_needed=2, B tem 2 ociosos) →
  B responde `response_accepted` com 2 em `worker_details` → emite
  `command_redirect` a cada um.
- **CT02** help recusado: B com carga alta → `response_rejected` reason
  `high_load`; nenhum `command_redirect`.
- **CT03** correlação: 2 `request_help` concorrentes para Masters distintos →
  cada resposta volta com o `request_id` idêntico e é correlacionada.
- **CT04** registro de emprestado: Worker conecta a A e envia
  `register_temporary_worker` → A registra como emprestado; nas tarefas seguintes
  o Worker envia `ALIVE` com `SERVER_UUID` = Master B.
- **CT05** tarefa em emprestado: A tem tarefa na fila e o emprestado pede
  trabalho → QUERY → STATUS OK → ACK; log indica execução por emprestado.
- **CT06** devolução: carga de A < liberação → `command_release` ao Worker +
  `notify_worker_returned` a B → Worker reconecta a B.
- **CT07** timeout: B não responde em 5s → A descarta `request_id`, loga e segue.
- **CT08** falha do receptor: A cai durante o empréstimo → emprestados detectam e
  tentam reconectar a B.
- **CT09** type desconhecido: B loga, ignora e continua operando.

**DoD (do PDF):** (2) A abre TCP com vizinho e envia `request_help`; (3) B
responde accepted/rejected com mesmo `request_id`; (4) após accepted, B redireciona
e Workers reconectam a A; (5) emprestados executam `register_temporary_worker` e
recebem tarefas com `SERVER_UUID`; (6) ao normalizar, A emite `command_release` +
`notify_worker_returned` e o Worker volta; (7) interopera com outra equipe só
pelos payloads; (8) parsing tolerante/controlado; (9) sem vazamento de
threads/conexões/mensagens após o ciclo.

## Pontos de atenção registrados

- **Thresholds default:** `capacity=100`, `release_threshold=60` (configuráveis).
- **Diretório de vizinhos estático** (pré-requisito 3); a descoberta da Sprint
  2.1 permanece no código mas não participa da negociação M2M.
- **Limitação do ambiente:** testes rodam em loopback (sem rede real). A
  interoperabilidade com outra equipe (DoD 7) é validada em ambiente externo,
  garantida pela aderência estrita aos payloads.

## Referências

- `plano_proj_SD-26_1.pdf` — "Sprint 03", estrutura M2M, 7 tipos, backlog
  (Tarefas 01–07), DoD, casos CT01–CT09, notas 31–38 e diagrama de fluxo.
- Specs anteriores: heartbeat, tarefas-workers, discovery-election.
