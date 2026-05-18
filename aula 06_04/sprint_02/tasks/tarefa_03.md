# Tarefa 03 — Transição UDP → TCP e Handshake Inicial

Resumo
-------
Depois de eleger um Master, o Worker deve estabelecer uma conexão TCP com o Master eleito e realizar um handshake de confirmação antes de iniciar o ciclo de Heartbeat.

Objetivo
--------
Garantir que a escolha do Master seja confirmada via conexão TCP e um ACK mútuo; somente após confirmação o Worker passa a enviar Heartbeats e executar tarefas dependentes do Master.

Passos do Handshake
-------------------
1. O Worker abre conexão TCP com `MASTER_IP:MASTER_PORT` do `selected_master` (timeout de conexão recomendado: 5s).
2. Após conexão, o Worker envia confirmação de eleição (exemplo):

```json
{"TYPE":"ELECTION_ACK","WORKER_UUID":"W-101","SELECTED_MASTER":"MASTER_1"}
```

3. O Master valida e responde via TCP com um ACK (exemplo):

```json
{"TYPE":"ELECTION_ACK","STATUS":"ACCEPTED","MASTER_NAME":"MASTER_1"}
```

4. Ao receber `STATUS: "ACCEPTED"`, o Worker inicia o loop de Heartbeat (Sprint 1) e considera a eleicao bem sucedida.

Tratamento de Erros
-------------------
- Se a conexão TCP falhar (timeout ou reset) ou o Master responder com `STATUS` diferente de `ACCEPTED`:
  - Invalidar cache de descoberta local para aquele Master.
  - Voltar ao fluxo de descoberta (Tarefa 01) e repetir (pode aplicar backoff).
- Se o handshake não completar no `handshake_timeout` (ex.: 5s), abortar e re-tentar descoberta/eleição.

Critérios de Aceitação
----------------------
- CT04: Se o Master eleito aceita (ACK recebido), o Worker inicia Heartbeat e passa para o estado `CONNECTED`.
- CT03/CT04 (falhas): em caso de falha de conexão, o Worker rejeita o Master e reinicia descoberta/eleição.

Notas de payloads e fluxo (resumo textual)
------------------------------------------
- DISCOVERY (UDP) → múltiplas DISCOVERY_REPLY (UDP unicast) → eleição determinística → TCP connect → ELECTION_ACK (Worker->Master) → ELECTION_ACK (Master->Worker, STATUS: ACCEPTED) → iniciar Heartbeat.

Exemplo de Heartbeat inicial (após ACK)

```json
{"TYPE":"HEARTBEAT","WORKER_UUID":"W-101","SERVER_UUID":"MASTER_1","TASK":"HEARTBEAT"}
```

Configurações recomendadas
--------------------------
- `tcp_connect_timeout`: 5s
- `handshake_timeout`: 5s
- `discovery_timeout`: 3s (conforme Tarefa 01)

