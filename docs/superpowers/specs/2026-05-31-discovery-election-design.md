# Sprint 2.1 — Descoberta Dinâmica e Eleição de Master pelos Workers — Design

Date: 2026-05-31
Depende de: Sprint 01 (Heartbeat) e Sprint 02 (Tarefas) — reaproveita `messaging`,
o ciclo de heartbeat e o ciclo de tarefas. A descoberta é o **estágio inicial**
que antecede o handshake TCP e alimenta esses ciclos já existentes.

## Resumo

- **Objetivo:** permitir que o Worker inicie **sem IP/porta do Master
  configurados**, descubra Masters na rede via **UDP**, eleja um de forma
  **determinística** (mesma escolha em todos os Workers, sem comunicação entre
  eles), faça a transição para **TCP**, confirme a eleição (ELECTION_ACK) e só
  então inicie o ciclo de Heartbeat (Sprint 01) e de tarefas (Sprint 02).
- **Decisão estrutural (aprovada):** pasta cumulativa `sprints/sprint02_1_discovery/`
  (cópia da `sprint02_tarefas` + camada de descoberta). Roda isolada.
- **Transporte (aprovado — abordagem A):** `asyncio` datagram endpoint, com a
  **lógica separada do transporte**. **Broadcast** (`255.255.255.255:5000`) como
  padrão (mais robusto em LAN/WiFi de sala de aula); **multicast**
  (`239.255.255.250`) disponível via flag.
- **Ambiente alvo:** várias máquinas na mesma LAN.

## Requisitos funcionais (extraídos do `discovery.pdf`)

- **Tarefa 01 — Canal de Descoberta (UDP):** Worker envia um pacote `DISCOVERY`
  via UDP ao iniciar; Masters escutam no mesmo grupo/porta e respondem via
  **unicast** ao IP de origem do Worker; janela fixa de coleta (3s).
- **Tarefa 02 — Eleição Determinística:** Worker coleta os Masters descobertos e
  aplica regra fixa e idêntica em todos: **menor `MASTER_NAME`** em ordem
  lexicográfica (com tratamento natural para `MASTER_1 < MASTER_2 < MASTER_10`).
  O eleito vira o alvo da conexão TCP.
- **Tarefa 03 — Transição UDP→TCP e Handshake:** Worker abre TCP com o
  `MASTER_IP`/`MASTER_PORT` do eleito, envia `ELECTION_ACK` e aguarda o ACK
  `ACCEPTED`; em sucesso, inicia o loop de Heartbeat.
- **Tarefa 04 — Resiliência e Reeleição:** sem respostas no timeout →
  `NO_MASTER_FOUND` + backoff exponencial + repete a descoberta; queda do TCP
  pós-eleição → invalida o cache de descoberta e reinicia o processo. Logs claros
  em cada etapa: `DISCOVERY`, `ELECTION`, `CONNECTING`, `FALLBACK`.

## Payloads oficiais (exatos do PDF — terminam com `\n`, controle em CAIXA ALTA)

**1. Solicitação de Descoberta (Worker → UDP Multicast/Broadcast)**
```json
{ "TYPE": "DISCOVERY", "WORKER_UUID": "W-101" }
```

**2. Resposta de Descoberta (Master → Worker, Unicast UDP)**
Obrigatórios: `TYPE`, `MASTER_NAME`, `MASTER_IP`, `MASTER_PORT`. (`STATUS:"AVAILABLE"`
aparece no fluxo de comunicação do PDF e é incluído.)
```json
{ "TYPE": "DISCOVERY_REPLY", "MASTER_NAME": "MASTER_1", "MASTER_IP": "192.168.1.20", "MASTER_PORT": 8000, "STATUS": "AVAILABLE" }
```

**3. Confirmação de Eleição (Worker → Master, TCP)**
```json
{ "TYPE": "ELECTION_ACK", "WORKER_UUID": "W-101", "SELECTED_MASTER": "MASTER_1" }
```

**4. ACK de Eleição (Master → Worker, TCP)**
```json
{ "TYPE": "ELECTION_ACK", "STATUS": "ACCEPTED", "MASTER_NAME": "MASTER_1" }
```

Após este ACK, o Worker inicia imediatamente o ciclo de Heartbeat da Sprint 01.

## Arquitetura proposta

Pacote estendido em `sprints/sprint02_1_discovery/src/heartbeat/`:

- **`messaging.py`** — reaproveitado (JSON + `\n`). A descoberta UDP usa o mesmo
  encode/decode; como UDP é orientado a datagrama (1 pacote = 1 mensagem), o
  `\n` é mantido por consistência de protocolo, mas o limite de mensagem é o
  próprio datagrama.
- **`discovery.py`** — NOVO. Lógica separada do transporte:
  - `parse_reply(raw) -> dict | None` — valida `DISCOVERY_REPLY`; retorna `None`
    e loga *warning* se faltar campo obrigatório (CT05).
  - `elect_master(replies) -> dict | None` — regra determinística: ordena por
    `MASTER_NAME` (chave natural: separa prefixo + número, p/ `MASTER_10` vir
    depois de `MASTER_2`) e devolve o menor; ignora os demais (CT02).
  - `DiscoveryProtocol(asyncio.DatagramProtocol)` — coleta respostas recebidas.
  - `async discover(worker_uuid, *, disc_port=5000, mode="broadcast",
    group="239.255.255.250", window=3.0) -> list[dict]` — envia `DISCOVERY`,
    coleta por `window` segundos, devolve as replies válidas.
  - Constantes de log: etapas `DISCOVERY`, `ELECTION`, `CONNECTING`, `FALLBACK`.
- **`master_async.py`** — ganha um **responder UDP** rodando junto do servidor
  TCP no mesmo event loop:
  - `MasterDiscoveryProtocol` — ao receber `DISCOVERY`, responde via unicast ao
    `addr` de origem com `DISCOVERY_REPLY` (nome, IP anunciado, porta TCP).
  - Novos atributos: `name` (`MASTER_1`...), `advertise_ip` (auto-detectado ou
    via CLI), `disc_port`.
  - No TCP, passa a tratar `ELECTION_ACK` (Worker→Master) respondendo
    `ACCEPTED` (Master→Worker). Heartbeat e tarefas seguem como antes.
- **`worker_async.py`** — novo fluxo de bootstrap antes do heartbeat:
  - `async bootstrap(worker_uuid, ...)` — `discover` → `elect_master` →
    (se vazio) `NO_MASTER_FOUND` + backoff e repete; senão `connect_and_confirm`.
  - `async connect_and_confirm(master, worker_uuid)` — abre TCP (timeout 5s),
    envia `ELECTION_ACK`, espera `ACCEPTED`; sucesso → retorna (host, port) e
    cai no `work_loop`/heartbeat existente; falha → invalida e refaz (CT04).
- **Entrypoints** `master.py` (agora com `--name`, `--disc-port`,
  `--advertise-ip`, `--discovery-mode`) e `worker.py` (sem `--host/--port` do
  Master; com `--discovery-mode`, `--disc-port`).

### Detecção do IP anunciado (LAN)

Em LAN o Master não pode anunciar `0.0.0.0`. O IP de saída é detectado abrindo
um socket UDP "discado" para um destino externo (ex.: `8.8.8.8:80`) e lendo
`getsockname()` — **não envia pacote algum**, apenas resolve qual interface o SO
usaria. Override manual via `--advertise-ip` para redes com múltiplas interfaces.

### Concorrência

Mantém o modelo single-thread do asyncio. O Master roda 2 endpoints no mesmo
loop (UDP responder + TCP server); as estruturas compartilhadas (fila/registro
da Sprint 02) continuam acessadas sem `await` no meio, dispensando locks.

## Fluxo de dados (bootstrap completo)

```
Worker (sem IP do Master)
  └─[UDP DISCOVERY broadcast:5000]→  (todos os Masters)
        Master_1 →[UDP unicast DISCOVERY_REPLY]→ Worker
        Master_2 →[UDP unicast DISCOVERY_REPLY]→ Worker
  [Worker aguarda 3s, coleta respostas]
  elect_master(...) → MASTER_1 (menor nome)
  └─[TCP connect MASTER_1.ip:port]→
  └─[TCP ELECTION_ACK + SELECTED_MASTER]→ Master_1
        Master_1 →[TCP ELECTION_ACK STATUS=ACCEPTED]→ Worker
  → inicia Heartbeat (Sprint 01) e ciclo de tarefas (Sprint 02)
```

## Erros, resiliência e logging

- **Strict parsing:** ignora campos desconhecidos; `DISCOVERY_REPLY` sem campo
  obrigatório (ex.: `MASTER_PORT`) é descartada com *warning*, sem interromper a
  coleta das demais (CT05).
- **Janela de coleta:** 3s fixos após o `DISCOVERY` (Nota 3 do PDF).
- **Sem Masters (CT03):** loga `NO_MASTER_FOUND`, aplica backoff exponencial
  (1s, 2s, 4s… teto) e repete a descoberta.
- **Queda pós-eleição (CT04):** timeout TCP de 5s; ao cair, invalida o cache de
  descoberta e reinicia (re-descobre e re-elege — pode reeleger o mesmo, se
  voltar).
- **Determinismo (O3):** a eleição depende só dos nomes recebidos; dois Workers
  que recebam o mesmo conjunto elegem o mesmo Master, sem se falarem.
- **Logs por etapa:** `DISCOVERY` (enviado/coletando), `ELECTION` (eleito X),
  `CONNECTING` (TCP), `FALLBACK` (backoff/reinício), além de `NO_MASTER_FOUND`.

## Testes e DoD (critérios de aceite)

**Unidade (sem rede):**
- `elect_master`: ordena lexicográfico/natural; entre `[MASTER_2, MASTER_1,
  MASTER_3]` elege `MASTER_1` (CT02); `[MASTER_2, MASTER_10]` elege `MASTER_2`.
- `parse_reply`: aceita reply completa; descarta sem `MASTER_PORT` (CT05);
  ignora campos extras.

**Integração (sockets reais em loopback):**
- **CT01** Um Master: Worker faz `discover` para `127.0.0.1:<porta>` e recebe 1
  `DISCOVERY_REPLY`; em seguida o handshake TCP `ELECTION_ACK`→`ACCEPTED`
  conclui e o primeiro Heartbeat responde `ALIVE`.
- **CT03** Nenhum Master: `discover` com janela curta sem responder → lista
  vazia → bootstrap loga `NO_MASTER_FOUND` e agenda retry (verificado sem
  loop infinito, com no máx. N tentativas injetadas).
- **CT04** Queda pós-eleição: após `ACCEPTED`, o Master fecha o TCP; o Worker
  detecta a perda e dispara o caminho de reinício (cache invalidado).
- **Handshake de eleição** ponta a ponta: `ELECTION_ACK`→`ACCEPTED` isolado.

> **Limitação do ambiente (sandbox sem rede):** broadcast/multicast atravessando
> máquinas **não é validável aqui** — os testes exercitam o datagrama UDP em
> loopback (unicast para `127.0.0.1`), que cobre todo o código de descoberta
> exceto o endereço de destino/binding. A validação multi-máquina fica na LAN,
> com a receita de 2 máquinas documentada no README.

**DoD (do PDF):**
1. Worker inicia sem IP/porta do Master configurados.
2. Faz descoberta via rede e lista os Masters respondentes.
3. Elege consistentemente o mesmo Master que outros Workers simultâneos
   (regra determinística por nome).
4. Estabelece TCP com o eleito e envia o primeiro Heartbeat com sucesso.
5. Trata timeout, ausência de Masters e queda pós-eleição.
6. Todos os payloads em JSON + `\n` com parsing estrito.

## Ponto de atenção registrado

- **Default broadcast vs multicast:** adotado **broadcast** como padrão (robustez
  em LAN/WiFi), com multicast via `--discovery-mode multicast`. Se o avaliador
  exigir multicast como padrão, troca-se o default da flag (uma linha).
- **`STATUS:"AVAILABLE"` na reply:** presente no fluxo do PDF; incluído no envio.
  Não é exigido no parsing (campo informativo), então sua ausência não invalida
  uma reply que tenha os obrigatórios.

## Referências

- `discovery.pdf` — "Sprint 2.1", "Objetivos", "Backlog", "DoD", "Payloads
  Oficiais", "Notas de Implementação", "Cenários de Teste (CT01–CT05)" e
  "Fluxo de Comunicação".
- Specs anteriores: `2026-05-30-heartbeat-design.md`,
  `2026-05-31-tarefas-workers-design.md`.
