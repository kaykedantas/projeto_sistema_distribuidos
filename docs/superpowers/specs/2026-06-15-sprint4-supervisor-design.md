# Sprint 4 — Supervisor de Métricas (performance_report) — Design

Date: 2026-06-15
Depende de: Sprint 01 (Heartbeat), Sprint 02 (Tarefas), Sprint 2.1 (Descoberta/Eleição),
Sprint 03 (Negociação M2M), Sprint 3.1 (Consolidação raiz), Sprint 3.2 (Tolerância a
falhas de tarefa).
Escopo: atua **exclusivamente** sobre o `master.py` consolidado na raiz do projeto.
As pastas `sprints/` e os módulos `src/heartbeat/` **não** são alterados.

## Contexto

A Sprint 4 ("Apresentação Final") integra o projeto a um **Supervisor de Métricas**
externo do professor. Cada farm (Master + seus Workers) envia, **a cada 10 segundos**,
um relatório `performance_report` em JSON por **TLS sobre TCP**. O supervisor agrega os
relatórios e exibe um dashboard web (`https://nuted-ia.dev/supervisor/dashboard/`) com
topologia, uso de CPU/memória/disco e estado de workers/tarefas em tempo real.

## Objetivo

Adicionar ao Master a capacidade de coletar métricas de sistema e de farm e reportá-las
ao supervisor de forma periódica, resiliente (nunca derrubando o Master) e aderente ao
schema do payload definido no PDF.

## Decisões de design (aprovadas no brainstorming)

1. **Fonte de métricas de sistema: `psutil` (obrigatório).** CPU%, memória, disco, load
   average e contagem de cores vêm de `psutil`, que funciona em qualquer SO (inclusive
   Windows, onde a stdlib não oferece load average nem CPU%). `psutil` entra no
   `requirements.txt` da raiz. Justificativa: a Sprint 4 exige métricas reais; aproximar
   tudo com stdlib produziria dados pobres no dashboard.

2. **Apenas o Master reporta (a farm inteira).** O PDF descreve `michel_1`/`michel_2`
   como "identificadores de **farms**". Uma farm = um Master + seus Workers, e todo o
   estado dos workers já vai embutido em `farm_state`. Workers não enviam relatório
   próprio — evita duplicar coleta/TLS no `worker.py` e mantém a lógica num arquivo só.

3. **Integração embutida no `master.py` (não módulo separado).** Mantém o padrão
   "arquivo único autossuficiente" da raiz. Uma nova seção "Sprint 4 — Supervisor" com
   três peças: builder do payload (função pura), sender TLS (fire-and-forget) e um loop
   asyncio em background disparado no `start()`.

4. **Dois identificadores distintos (não confundir).**
   - `master_id` / `name` = **`MASTER_9`** — identidade do nó no cluster (discovery,
     eleição, M2M). Inalterado.
   - `server_uuid` do payload = **`michel_1`** (default, configurável via
     `--supervisor-uuid`) — identidade da farm perante o supervisor. O valor real é o que
     o professor atribuir à farm (`michel_1` ou `michel_2`).

5. **Fire-and-forget resiliente.** Conecta via TLS, envia o JSON (+`\n`) e fecha. Sem
   `recv`, sem HTTP, sem path — apenas host:porta. Cada envio é protegido por
   `try/except`: falha de rede/TLS gera log `WARNING` e o Master continua normalmente.

6. **Resolução da contradição do PDF.** O texto cita de passagem "porta 8000", mas a
   seção "Parâmetros da conexão" é explícita: `nuted-ia.dev:443`, TLS, SNI `nuted-ia.dev`.
   Adotamos `443/TLS`. Tudo configurável por constante e CLI.

## Arquitetura e fluxo

```
start()
  └── asyncio.gather(serve_forever(), _stdin_task_feeder(), _supervisor_loop())

_supervisor_loop()  (a cada supervisor_interval = 10s)
  ├── payload = build_performance_report(self)      # função pura, testável
  ├── await send_report_tls(payload, host, port)    # TLS, fire-and-forget
  └── try/except -> WARNING e continua               # nunca derruba o Master
```

## Builder do payload — mapeamento dos campos

`build_performance_report(master) -> dict` é uma **função pura** (recebe o Master e o
momento atual; não faz I/O de rede). As métricas de `psutil` são lidas e injetadas.

### Topo

| Campo | Fonte |
|---|---|
| `server_uuid` | `master.supervisor_uuid` (default `michel_1`) |
| `hostname` | `socket.gethostname()` |
| `role` | `"master"` |
| `task` | `"performance_report"` |
| `timestamp` | `datetime.now(timezone.utc)` em ISO-8601 `YYYY-MM-DDTHH:MM:SSZ` |
| `message_id` | `uuid4()` |
| `payload_version` | `"sprint4-monitor"` |

### performance.system (psutil)

| Campo | Fonte |
|---|---|
| `uptime_seconds` | `int(time.time() - master._start_time)` (uptime do processo) |
| `load_average_1m` / `load_average_5m` | `psutil.getloadavg()` |
| `cpu.usage_percent` | `psutil.cpu_percent()` |
| `cpu.count_logical` / `count_physical` | `psutil.cpu_count(logical=True/False)` |
| `memory.total_mb` / `available_mb` / `memory_used` | `psutil.virtual_memory()` (bytes→MB) |
| `memory.percent_used` | `psutil.virtual_memory().percent` |
| `disk.total_gb` / `free_gb` / `percent_used` | `psutil.disk_usage(<raiz>)` (bytes→GB) |

### performance.farm_state.workers

| Campo | Fonte |
|---|---|
| `total_registered` | `len(master.workers)` |
| `workers_utilization` | `len(master.in_flight)` (ocupados executando) |
| `workers_alive` | `len(master.workers)` *(aproximação — ver abaixo)* |
| `workers_idle` | `len(master.idle_workers)` |
| `workers_borrowed` | `len(master.lent_out)` (emprestados para fora) |
| `workers_received` | `len(master.borrowed_in)` (recebidos de outros) |
| `workers_failed` | `master.workers_failed` *(novo contador)* |
| `workers_home` | locais = `total_registered − workers_received` |
| `workers_available_capacity` | `= workers_idle` (conforme nota do PDF) |
| `borrowed_workers[]` | `lent_out` (`direction:"out"`) + `borrowed_in` (`direction:"in"`) |

### performance.farm_state.tasks

| Campo | Fonte |
|---|---|
| `tasks_pending` | `len(master.tasks)` |
| `tasks_running` | `len(master.in_flight)` |
| `tasks_completed` | `master.tasks_completed` *(novo: ++ em STATUS OK)* |
| `tasks_failed` | `master.tasks_failed` *(novo: ++ em STATUS NOK)* |
| `oldest_task_age_s` | a partir dos **timestamps de enfileiramento** (novo) |

### performance.config_thresholds

| Campo | Fonte |
|---|---|
| `max_task` | `master.capacity` |
| `warn_cpu_percent` | `master.warn_cpu_percent` (default 85) |
| `warn_memory_percent` | `master.warn_memory_percent` (default 85) |
| `release_task` | `master.release_threshold` |

### performance.neighbors[]

| Campo | Fonte |
|---|---|
| `server_uuid` | chave de `master.neighbors` |
| `status` | `"available"`/`"unavailable"` via checagem leve de alcançabilidade |
| `last_heartbeat` | timestamp atual se alcançável *(aproximação)* |

## Aproximações assumidas (declaradas)

O modelo atual não mantém alguns dados finos; assumimos aproximações honestas e
documentadas, em vez de inventar precisão:

- `workers_alive` ≈ `total_registered` (não há ping contínuo por worker; o heartbeat é
  iniciado pelo worker, não sondado pelo master).
- `workers_failed` = contador incrementado quando um worker cai com tarefa em andamento
  (reaproveita o ponto de reenfileiramento da Sprint 3.2).
- `neighbors[].last_heartbeat` = momento da coleta quando o vizinho responde à checagem
  TCP; não há histórico de heartbeats M2M.

## Estado novo no Master

- `self._start_time = time.time()` — base do `uptime_seconds`.
- `self.tasks_completed = 0`, `self.tasks_failed = 0`, `self.workers_failed = 0`.
- **Timestamps de enfileiramento** para `oldest_task_age_s`: as quatro mutações de
  `self.tasks` (`append`, `appendleft`×2, `popleft`) passam a usar helpers internos
  (`_enqueue`, `_enqueue_front`, `_dequeue`) que mantêm uma deque paralela de tempos em
  sincronia. Efeito colateral positivo: centraliza e clarifica o código at-least-once da
  Sprint 3.2.

## Configuração (constantes + CLI)

| Constante | Default | CLI |
|---|---|---|
| `DEFAULT_SUPERVISOR_UUID` | `"michel_1"` | `--supervisor-uuid` |
| `DEFAULT_SUPERVISOR_HOST` | `"nuted-ia.dev"` | `--supervisor-host` |
| `DEFAULT_SUPERVISOR_PORT` | `443` | `--supervisor-port` |
| `DEFAULT_SUPERVISOR_INTERVAL` | `10.0` | `--supervisor-interval` |
| `DEFAULT_WARN_CPU` | `85` | `--warn-cpu` |
| `DEFAULT_WARN_MEM` | `85` | `--warn-mem` |
| (liga/desliga) | ligado | `--no-supervisor` (desliga, p/ testes offline) |

## Conexão TLS

- `ssl.create_default_context()` com `server_hostname=SNI` (validação de certificado
  padrão). Em falha de handshake/conexão: log `WARNING`, sem exceção propagada.
- Envio: `writer.write(json + "\n")`, `await writer.drain()`, fecha. Nenhum `recv`.

## Tratamento de erros (invariante)

O loop do supervisor **nunca** pode derrubar o Master. Todas as falhas (DNS, conexão
recusada, timeout, erro de TLS, supervisor fora do ar) são capturadas, logadas como
`WARNING` e seguidas de novo ciclo após o intervalo.

## Testes

`test_supervisor.py` (raiz, sem dependências de rede):

1. **Builder** — com `psutil` mockado (valores fixos) e um Master de estado conhecido
   (tarefas, idle/borrowed/lent workers, vizinhos), validar que `build_performance_report`
   produz todos os campos obrigatórios, com tipos corretos e o mapeamento esperado.
2. **Contadores** — `STATUS OK` incrementa `tasks_completed`; `STATUS NOK` incrementa
   `tasks_failed`.
3. **oldest_task_age_s** — após enfileirar tarefas, o valor reflete a idade da mais antiga.
4. **Sender resiliente** — `send_report_tls` para host inalcançável **não** lança exceção.

O envio TLS real contra `nuted-ia.dev:443` (precisa de internet) é verificação **manual**,
coberta no checklist da Definição de Pronto — não em teste automático.

## Definição de "Pronto" (DoD) — Sprint 4

- [x] O Master coleta métricas de sistema (psutil) e de farm a cada 10s.
- [x] O payload segue o schema do PDF (todos os campos, tipos e blocos).
- [x] O envio é TLS sobre TCP para `nuted-ia.dev:443` com SNI, sem HTTP e sem `recv`.
- [x] `server_uuid` = `michel_1`/`michel_2` (configurável), distinto de `master_id`.
- [x] Falha do supervisor não derruba o Master (log e continua).
- [x] Envio real confirmado: `relatório enviado a nuted-ia.dev:443 (1069 bytes)` (TLS+SNI+cert ok).
- [ ] Conferir visualmente a farm `michel_1` no dashboard do professor (passo manual restante).
- [x] Testes automáticos do builder, contadores e sender passam (6/6).

## Invariantes preservados

- **Protocolo de fio do cluster inalterado** — os payloads das Sprints 01–03 não mudam.
  A Sprint 4 só **adiciona** um canal de saída (Master → Supervisor).
- **Nenhuma alteração em `sprints/` ou `src/heartbeat/`.**
- **Sem locks** — coleta e envio ocorrem no mesmo event loop asyncio single-thread.

## Divergência conhecida

A funcionalidade vive apenas no `master.py` consolidado (o que é executado). O módulo
`src/heartbeat/master_async.py` (usado pelos 54 testes das pastas `sprints/`) não recebe
a mudança. Portar é opcional.

## Referências

- `plano_proj_SD-26_1 (1).pdf` — seção "SPRINT 4 - APRESENTAÇÃO FINAL", schema do
  `performance_report`, parâmetros de conexão e observações sobre `server_uuid`.
- Texto extraído: `plano_text_v2.txt` (linhas ~2336–2612).
- Specs anteriores: `2026-06-02-sprint31-correcoes-design.md`,
  `2026-06-09-tolerancia-falha-tarefas-design.md`.
