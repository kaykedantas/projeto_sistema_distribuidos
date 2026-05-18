# Descoberta Dinâmica e Eleição de Master — Design
Data: 2026-05-18

Resumo
-------
Documento de design para o mecanismo de descoberta em rede, eleição determinística de Master e confirmação via TCP (handshake). Este design concretiza as Tarefas 01–03 descritas em `tasks/tarefa_01.md`, `tasks/tarefa_02.md` e `tasks/tarefa_03.md`.

Contexto e Escopo
------------------
- Escopo: Implementar detecção de Masters via UDP (modo multicast por padrão), eleição determinística entre respostas e confirmação via TCP antes de iniciar o Heartbeat.
- Não inclui: protocolos de alta disponibilidade complexos (ex.: Raft), persistência além de caches em memória, ou mudanças fora das áreas listadas.

Configurações padrão (confirmadas)
----------------------------------
- modo_descoberta: multicast
- multicast_address: 239.255.255.250
- discovery_port: 5000
- discovery_timeout: 3000 ms
- tcp_connect_timeout: 5000 ms
- handshake_timeout: 5000 ms
- retry_backoff_initial: 1000 ms
- retry_backoff_factor: 2
- retry_backoff_max: 30000 ms

Arquitetura e Componentes
-------------------------
- Worker: agente que inicia descoberta, executa eleição e mantém Heartbeat.
- Master: responde a DISCOVERY (UDP) e aceita conexões TCP para handshake/Heartbeats.
- Módulo de Descoberta (`src/discovery.py`): abstrai envio de DISCOVERY, coleta de respostas e parsing estrito.
- Módulo de Eleição (`src/election.py`): aplica regra determinística de seleção.
- Módulo de Handshake (`src/handshake.py`): estabelece TCP e confirma eleição.
- Config/Logging: centralizar parâmetros em `config.yaml` ou variáveis de ambiente; logs com níveis `INFO/WARN/ERROR`.

Fluxo de Alto Nível
-------------------
1. Worker envia DISCOVERY (UDP multicast) com payload JSON: {"TYPE":"DISCOVERY","WORKER_UUID":"W-101"}.
2. Masters escutam e respondem via UDP unicast ao Worker com DISCOVERY_REPLY contendo `MASTER_NAME`, `MASTER_IP`, `MASTER_PORT`, `STATUS`.
3. Worker coleta respostas por `discovery_timeout` (3000 ms), valida JSON estritamente e descarta respostas malformadas.
4. Worker aplica a regra de eleição (ordenar por `MASTER_NAME` lexicograficamente, critério secundário `MASTER_IP`) e escolhe `selected_master`.
5. Worker abre conexão TCP com `MASTER_IP:MASTER_PORT` e envia ELECTION_ACK; Master responde com ACK `STATUS: ACCEPTED` para confirmar.
6. Ao receber `ACCEPTED`, Worker inicia loop de Heartbeat; em qualquer falha de handshake, Worker invalida cache e reinicia descoberta com backoff.

Mensagens / Payloads (exemplos)
-------------------------------
- DISCOVERY (Worker → multicast UDP):

```json
{"TYPE":"DISCOVERY","WORKER_UUID":"W-101"}
```

- DISCOVERY_REPLY (Master → Worker UDP unicast):

```json
{
  "TYPE": "DISCOVERY_REPLY",
  "MASTER_NAME": "MASTER_1",
  "MASTER_IP": "192.168.1.20",
  "MASTER_PORT": 6000,
  "STATUS": "AVAILABLE"
}
```

- ELECTION_ACK (Worker → Master TCP):

```json
{"TYPE":"ELECTION_ACK","WORKER_UUID":"W-101","SELECTED_MASTER":"MASTER_1"}
```

- ELECTION_ACK (Master → Worker TCP, confirmação):

```json
{"TYPE":"ELECTION_ACK","STATUS":"ACCEPTED","MASTER_NAME":"MASTER_1"}
```

Requisitos Funcionais (resumo)
------------------------------
- R1: Workers devem descobrir Masters sem configuração manual de IP/porta.
- R2: Registro e coleta de respostas dentro de `discovery_timeout`.
- R3: Eleição determinística reproduzível por qualquer Worker com o mesmo conjunto de respostas.
- R4: Confirmação via TCP antes de iniciar Heartbeat; sem confirmação não alterar estado para CONNECTED.
- R5: Robustez contra respostas malformadas, timeouts e conexões TCP falhas (invalidar e reiniciar).

Critérios de Aceitação (mapa para CTs)
-------------------------------------
- CT01 (único Master disponível): Worker conecta e entra no Heartbeat.
- CT02 (múltiplos Masters): Workers elegem `MASTER_1` quando for lexicograficamente menor.
- CT03 (nenhum Master responde): Worker registra `NO_MASTER_FOUND` e aplica backoff.
- CT04 (Master eleito falha no TCP): Worker invalida cache e reinicia descoberta/eleição.
- CT05 (payload malformado): Master ignora e Worker continua com respostas válidas.

Cenários de Teste (sugestões)
---------------------------
- CT01: ambiente com um Master — Worker recebe resposta e completa handshake.
- CT02: múltiplos Masters com nomes `MASTER_1`, `MASTER_2`, `MASTER_3` — Worker elege `MASTER_1`.
- CT03: nenhum Master — timeout 3s, registra e repete com backoff.

Observabilidade e Logs
----------------------
- Log levels: `INFO` para eventos esperados (descoberta iniciada/recebida), `WARN` para respostas malformadas, `ERROR` para falhas de handshake repetidas.
- Emitir métricas: `discoveries_sent`, `discoveries_responses_count`, `elections_performed`, `handshake_failures`.

Segurança e Robustez
--------------------
- Validação estrita de JSON (campos obrigatórios e tipos).
- Ignorar/registrar payloads com conteúdo inesperado.
- Timeouts conservadores para evitar bloqueios.

Notas de Auto-revisão
---------------------
- Regra de eleição definida (lexicográfica por `MASTER_NAME`, secundário `MASTER_IP`).
- Todos os campos obrigatórios para DISCOVERY_REPLY especificados.
- Valores padrão alinhados com confirmação do usuário.

Próximo passo
-------------
Espec escrito e salvo em `docs/superpowers/specs/2026-05-18-discovery-election-design.md`. Por favor revise este documento; após sua aprovação eu executo o plano de implementação descrito em `docs/superpowers/plans/2026-05-18-discovery-election-plan.md`.
