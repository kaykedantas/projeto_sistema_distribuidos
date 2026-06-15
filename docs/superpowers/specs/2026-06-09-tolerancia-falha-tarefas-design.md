# Sprint 3.2 — Tolerância a Falhas de Tarefa (entrega at-least-once) — Design

Date: 2026-06-09
Depende de: Sprint 02 (Tarefas), Sprint 03 (Negociação M2M), Sprint 3.1 (Consolidação).
Escopo: atua **exclusivamente** sobre o `master.py` consolidado na raiz do projeto.
As pastas `sprints/` e os módulos `src/heartbeat/` **não** são alterados.

## Contexto

Em testes reais com dois Masters em máquinas distintas surgiram dois cenários de
**perda de tarefa**:

1. **Worker emprestado cai no meio da tarefa.** O Master A entrega `QUERY` a um Worker
   emprestado; o host do Worker perde a conexão antes de reportar `STATUS`. A tarefa
   nunca é concluída nem reentregue.
2. **Master perde a rede e volta.** As tarefas que já haviam sido entregues (e estavam
   "em andamento" quando a rede caiu) desaparecem; apenas tarefas novas passam a ser
   distribuídas.

## Causa raiz

A entrega de tarefas era **"fire-and-forget"**:

- `_handle_apresentacao` fazia `self.tasks.popleft()` e enviava o `QUERY` — a partir daí
  a tarefa não existia em estrutura alguma (não havia registro de "em andamento").
- `_handle_status` apenas incrementava um contador e respondia `ACK`. Um `STATUS` que
  nunca chega (Worker caído) não disparava nada.
- O `finally` de `handle_client` apenas fechava a conexão — sem devolver à fila a tarefa
  que aquele Worker estava processando.

Nenhuma sprint anterior implementou rastreamento de tarefa em andamento, reentrega ou
durabilidade. A resiliência existente (backoff/reconexão na Sprint 01; CT08 na Sprint 03)
é toda **de conexão**, não de tarefa — o PDF não exigia entrega durável.

## Decisão de design (aprovada)

Implementar **entrega at-least-once no lado do Master** (o Worker já reconecta sozinho
via `work_loop`, então não precisa de mudança):

1. **Rastreamento por conexão (`ctx`).** Cada conexão em `handle_client` mantém
   `ctx = {"uuid", "task"}`. Ao entregar `QUERY`, a tarefa é gravada em `ctx`.
   - A autoridade do reenfileiramento on-disconnect é o `ctx` **por conexão**, e não um
     dicionário global por UUID — isso evita a corrida em que o mesmo UUID reconecta
     (nova tarefa) antes do EOF da conexão antiga ser tratado.
2. **Reenfileiramento on-disconnect.** No `finally` de `handle_client`, se `ctx["task"]`
   ainda existe, a tarefa volta para a **frente** da fila (`appendleft`). Falha de
   infraestrutura **não** consome tentativa.
3. **Retentativa por NOK com limite.** `_handle_status` consome a tarefa do `ctx`;
   em `OK` zera o contador; em `NOK` reenfileira incrementando `task_attempts[user]`.
   Ao atingir `max_task_attempts` (padrão 3), a tarefa é **descartada** com log de
   *dead-letter* — evitando loop infinito de retentativa.
4. **Observabilidade.** `self.in_flight` (espelho `uuid -> user`) exibido em `/workers`;
   logs `WARNING`/`ERROR` em cada reenfileiramento e descarte.

### Configuração

- Constante `DEFAULT_MAX_TASK_ATTEMPTS = 3`; CLI `--max-attempts N`.

### Cenário 2 (persistência) — fora de escopo

O usuário confirmou que no Cenário 2 **apenas a rede caiu** (o processo do Master
continuou vivo), então o reenfileiramento on-disconnect já o cobre. Persistência em
disco (sobreviver ao **restart do processo**) fica como evolução futura (Parte B).

## Protocolo de fio

**Inalterado.** Os payloads (`WORKER:ALIVE`, `QUERY`, `STATUS`, `ACK`) são idênticos ao
PDF — a interoperabilidade com a implementação de outra equipe é preservada. Toda a
lógica nova é interna ao Master.

## Tradeoff

Entrega at-least-once admite **processamento duplicado**: se o Worker concluiu a tarefa
mas o `STATUS` se perdeu na queda, a tarefa reentregue será processada de novo. É o
tradeoff padrão (at-least-once vs. exactly-once) e aceitável para esta simulação.

## Testes

`test_task_recovery.py` (raiz, sem dependências) — 4 testes e2e contra sockets reais:
- `test_disconnect_reenfileira` — queda no meio → tarefa volta à fila (Cenário 1).
- `test_nok_reenfileira` — NOK → reenfileira; `task_attempts` incrementa.
- `test_nok_deadletter_no_limite` — NOK acima do limite → descarte.
- `test_ok_conclui` — OK → não reenfileira; `in_flight`/`task_attempts` limpos.

## Divergência conhecida

A correção vive apenas no `master.py` consolidado (o que é executado). O módulo
`src/heartbeat/master_async.py` (usado pelos 54 testes das pastas `sprints/`) **não**
recebeu a mudança e continua "fire-and-forget". Portar para lá é opcional — registrar
caso se queira manter paridade total entre as duas formas do sistema.

## Referências

- `plano_proj_SD-26_1.pdf` — Notas 31 (strict parsing), 38 (atomicidade).
- Specs anteriores: `2026-06-02-sprint31-correcoes-design.md` (consolidação raiz).
