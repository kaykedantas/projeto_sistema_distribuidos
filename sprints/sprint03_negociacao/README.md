# Sprint 3 — Protocolo de Negociacao Master-to-Master e Emprestimo de Workers

Os Masters passam a se comunicar entre si (P2P): um Master **saturado** negocia e
recebe Workers **emprestados** de um vizinho, opera com eles pelo ciclo de tarefas
(Sprint 02, via `SERVER_UUID`) e os **devolve** quando a carga normaliza. Esta
pasta e **cumulativa** (Sprint 01 + 02 + 2.1 + negociacao).

> **Nao ha eleicao de lider.** Masters sao peers iguais; "consenso" aqui significa
> apenas que os dois concordam sobre o emprestimo (um pede, o outro aceita). A
> eleicao Worker->Master (Sprint 2.1) permanece no codigo, sem ser acionada aqui.

## Estrutura

```
master.py / worker.py          # entrypoints (Master vira peer P2P)
src/heartbeat/
  messaging.py                 # JSON + \n (reaproveitado)
  m2m.py                       # NOVO: envelope M2M + 7 construtores
  master_async.py              # + carga/histerese + negociacao + emprestimo
  worker_async.py              # + command_redirect / command_release
  discovery.py                 # Sprint 2.1 (presente, nao acionado pela negociacao)
tests/                         # 54 testes (sprints 01, 02, 2.1 e 3)
scripts/run_negociacao_demo.py # demo do ciclo completo de emprestimo/devolucao
run_tests.py                   # runner SEM dependencias
```

## Envelope padrao M2M

```json
{ "type": "<tipo>", "request_id": "<uuid_v4>", "payload": { } }
```

## Os 7 tipos de mensagem (payloads do PDF)

| # | type | Direcao |
|---|------|---------|
| 1 | `request_help` | Master A -> Master B |
| 2a | `response_accepted` | Master B -> Master A (mesmo request_id) |
| 2b | `response_rejected` | Master B -> Master A (reason: high_load / no_workers_available / refused) |
| 3 | `command_redirect` | Master B -> Worker |
| 4 | `register_temporary_worker` | Worker -> Master A |
| 5 | `command_release` | Master A -> Worker |
| 6 | `notify_worker_returned` | Master A -> Master B |

## Fluxo completo

```
Master A (load > capacity)
  A -> B : request_help {master_id, current_load, capacity, workers_needed}
  B -> A : response_accepted {workers_offered, worker_details[]} | response_rejected {reason}
  B -> W : command_redirect {new_master_address}
  W -> A : register_temporary_worker {worker_id, original_master_address}
  [W opera sob A — Sprint 02 com SERVER_UUID]
Master A (load < release_threshold)
  A -> W : command_release {original_master_address}
  A -> B : notify_worker_returned {worker_id}
  [W reconecta a B]
```

## Carga e histerese

`set_load(n)` dispara a negociacao quando `n > capacity` (default 100) e a
devolucao quando `n < release_threshold` (default 60). A zona morta entre 60 e
100 evita o efeito ping-pong (emprestar/devolver o mesmo worker repetidamente).

## Como executar — dois Masters + Worker (loopback)

```bash
# Terminal 1 — Master B (cede workers)
python master.py --id MASTER_B --name MASTER_B --port 8001 --disc-port 0

# Terminal 2 — Master A (pede ajuda), conhece B como vizinho
python master.py --id MASTER_A --name MASTER_A --port 8000 --disc-port 5000 \
  --neighbors MASTER_B@127.0.0.1:8001 --capacity 100 --release-threshold 60

# Terminal 3 — Worker (descobre A pela Sprint 2.1 e opera)
python worker.py --uuid W-101 --disc-port 5000
```

Demo automatica do ciclo completo (um processo):

```bash
python scripts/run_negociacao_demo.py
```

## Testes

```bash
python run_tests.py          # 54 testes (sem dependencias): sprints 01, 02, 2.1 e 3
# ou: pip install -r requirements.txt && pytest -q
```

> **Nota sobre o ambiente.** Os testes rodam em loopback (sem rede real). A
> interoperabilidade com a implementacao de outra equipe (DoD 7) e validada em
> ambiente externo, garantida pela aderencia estrita aos payloads do PDF.

## Definicao de "Pronto" (DoD) — Sprint 3

- [x] **2.** Master A abre TCP com vizinho e envia `request_help`.
- [x] **3.** Master B responde `response_accepted`/`response_rejected` com o mesmo `request_id`.
- [x] **4.** Apos aceite, B redireciona Workers e eles se reportam a A.
- [x] **5.** Emprestados executam `register_temporary_worker` e recebem tarefas com `SERVER_UUID`.
- [x] **6.** Ao normalizar, A emite `command_release` + `notify_worker_returned` e o Worker volta.
- [x] **7.** Interopera com outra equipe apenas pelos payloads (aderencia estrita).
- [x] **8.** Parsing tolerante (campos extras ignorados; obrigatorio ausente -> log).
- [x] **9.** Sem vazamento de conexoes/mensagens apos o ciclo.

Casos de teste cobertos: **CT01** (help aceito), **CT02** (recusado), **CT03**
(correlacao request_id concorrente), **CT04** (registro de emprestado), **CT05**
(tarefa em emprestado), **CT06** (devolucao + histerese), **CT07** (timeout 5s),
**CT08** (queda do receptor), **CT09** (type desconhecido).
