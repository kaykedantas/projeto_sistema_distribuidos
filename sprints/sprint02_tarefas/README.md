# Sprint 02 — Comunicação de Tarefas e Apresentação de Workers

Implementa o ciclo de vida completo de uma tarefa entre **Worker** e **Master**:
apresentação (com identificação de origem) → distribuição de tarefa → processamento
→ reporte de status → confirmação (ACK). Esta pasta é **cumulativa**: contém toda a
lógica da Sprint 01 (Heartbeat) mais as adições da Sprint 02.

## Estrutura

```
master.py                      # entry point do Master
worker.py                      # entry point do Worker
src/heartbeat/
  messaging.py                 # JSON delimitado por \n (reaproveitado da Sprint 01)
  master_async.py              # Master: heartbeat + fila de tarefas + ACK
  worker_async.py              # Worker: heartbeat + loop de trabalho
tests/                         # testes da Sprint 01 + Sprint 02 (CT01–CT05, ciclo)
scripts/run_tarefas_demo.py    # demo automática do ciclo de tarefas
scripts/run_heartbeat_demo.py  # demo de heartbeat (Sprint 01)
run_tests.py                   # runner de testes SEM dependências
```

## Payloads oficiais (do plano do projeto)

| # | Direção | Payload |
|---|---------|---------|
| 2.1 | Worker → Master | `{"WORKER":"ALIVE","WORKER_UUID":"W-123"}` |
| 2.1b | Worker → Master (emprestado) | `{"WORKER":"ALIVE","WORKER_UUID":"W-999","SERVER_UUID":"Master-B"}` |
| 2.2 | Master → Worker (tem tarefa) | `{"TASK":"QUERY","USER":"Michel"}` |
| 2.3 | Master → Worker (fila vazia) | `{"TASK":"NO_TASK"}` |
| 2.4 | Worker → Master (status) | `{"STATUS":"OK\|NOK","TASK":"QUERY","WORKER_UUID":"W-123"}` |
| 2.5 | Master → Worker (ACK) | `{"STATUS":"ACK","WORKER_UUID":"W-123"}` |

Regras: strict parsing (ignora campos extras; falha controlada se faltar
obrigatório), valores de controle em CAIXA ALTA, timeout de 5s no Worker.

> **Nota sobre o ACK:** o PDF diverge — o backlog/casos de sala mostram
> `{"STATUS":"ACK"}` e a seção "Payload Padrão" mostra `{"STATUS":"ACK","WORKER_UUID":"..."}`.
> Aqui o Master envia a versão **com** `WORKER_UUID` (correlação) e o Worker
> aceita as duas formas. Para o ACK "pelado", basta remover o campo no
> `_handle_status` de `master_async.py`.

## Como executar

Master (servidor), semeando a fila de tarefas:

```bash
python master.py --host 0.0.0.0 --port 8000 --tasks Michel,Julia
```

Worker local:

```bash
python worker.py --host 127.0.0.1 --port 8000 --uuid W-123
```

Worker emprestado (de outro Master):

```bash
python worker.py --host 127.0.0.1 --port 8000 --uuid W-999 --origin-master Master-B
```

Demo automática (Master + ciclos QUERY→STATUS→ACK e NO_TASK):

```bash
python scripts/run_tarefas_demo.py
```

O heartbeat da Sprint 01 continua disponível: `python worker.py --mode heartbeat`.

## Testes

```bash
python run_tests.py          # sem dependências (18 testes: Sprint 01 + 02)
# ou, com pytest:
pip install -r requirements.txt && pytest -q
```

## Definição de "Pronto" (DoD) — Sprint 02

- [x] **1.** Worker faz o handshake de apresentação (envia `WORKER_UUID`).
- [x] **2.** Master distribui uma tarefa real da fila (`QUERY`) ou informa `NO_TASK`.
- [x] **3.** Worker processa a tarefa e o Master recebe `OK`/`NOK`.
- [x] **4.** Worker recebe o `ACK` final, fechando o ciclo sem erros de parsing.
- [x] **5.** Sistema trata corretamente presença/ausência de `SERVER_UUID`
  (worker local vs. emprestado).

Casos de sala cobertos por testes automatizados: **CT01** (local→QUERY),
**CT02** (emprestado→QUERY + registro), **CT03** (fila vazia→NO_TASK),
**CT04** (OK→ACK), **CT05** (NOK→ACK), além do ciclo completo end-to-end.
