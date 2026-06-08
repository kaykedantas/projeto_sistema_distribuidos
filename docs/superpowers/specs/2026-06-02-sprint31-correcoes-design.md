# Sprint 3.1 — Correções de Integração dos Arquivos Unificados — Design

Date: 2026-06-02
Depende de: Sprint 01 (Heartbeat), Sprint 02 (Tarefas), Sprint 2.1 (Descoberta/Eleição),
Sprint 03 (Negociação M2M). Esta sprint NÃO altera as pastas `sprints/` existentes —
atua exclusivamente sobre os arquivos consolidados `master.py` e `worker.py` na raiz do
projeto.

## Contexto

Os arquivos `master.py` e `worker.py` foram criados como consolidação de todos os
módulos das Sprints 01, 02, 2.1 e 03 em dois arquivos autossuficientes. Na inspeção
pós-criação foram identificados **5 problemas** que impedem o funcionamento correto em
sala de aula (dois Masters em máquinas distintas na mesma LAN).

## Problemas identificados e suas causas

### Bug 1 — Porta UDP de descoberta divergente (CRÍTICO)

| Arquivo | Constante | Valor incorreto | Valor correto |
|---------|-----------|----------------|---------------|
| `worker.py` | `DEFAULT_DISC_PORT` | `5001` | `5000` |

**Causa:** Alteração manual de configuração sem atualizar o worker junto. O worker
envia `DISCOVERY` para a porta 5001, enquanto o master escuta na 5000. O worker nunca
recebe `DISCOVERY_REPLY` e nunca encontra o master. O modo padrão do worker é
`discovery`, logo **nenhuma conexão é estabelecida** pelo fluxo normal.

**Por que é crítico:** afeta as Sprints 2.1 e 3 inteiramente (modo padrão). As Sprints
01/02 no modo `--mode heartbeat` / `--mode tasks` com IP/porta fixos não são afetadas.

---

### Bug 2 — Histerese de carga invertida (Sprint 3 quebrada)

| Constante | Valor incorreto | Valor correto | Regra |
|-----------|----------------|---------------|-------|
| `DEFAULT_CAPACITY` | `1` | `100` | threshold de saturação |
| `DEFAULT_RELEASE_THRESHOLD` | `10` | `60` | **deve ser < capacity** |

**Causa:** Valores de teste deixados nas constantes. Com `capacity=1` e
`release_threshold=10`, a condição `release_threshold < capacity` é violada. O efeito:
- O master satura com apenas 1 tarefa na fila (`load > 1`).
- Na chamada seguinte a `set_load()`, como `load < 10` é quase sempre verdade, o master
  libera imediatamente — sem nunca passar pelo "dead zone" `[60, 100]`.
- A histerese deixa de existir: o master entra em ping-pong saturação/liberação.

**Referência do PDF (Nota 35):** `release_threshold < capacity` evita emprestar e devolver
o mesmo Worker imediatamente. Valores canônicos: capacity=100, release_threshold=60.

---

### Bug 3 — `set_load()` nunca chamado internamente

**Causa:** O método `set_load(n)` existe e está correto, mas nenhum código interno do
master o invoca. A carga (`current_load`) fica em 0 para sempre, logo `on_saturation`
nunca é disparado e a negociação M2M não começa automaticamente.

**Solução:** chamar `set_load(len(self.tasks))`:
- No `__init__`, após popular a fila inicial (para que a saturação seja detectada se as
  tarefas iniciais já excedem `capacity`).
- Em `_handle_apresentacao`, após retirar uma tarefa da fila (`popleft`), para refletir
  a nova carga.

---

### Bug 4 — `idle_workers` nunca populado automaticamente

**Causa:** Quando um worker se apresenta e recebe `NO_TASK` (fila vazia), ele é
registrado em `self.workers` mas jamais adicionado a `self.idle_workers`. O master B
nunca tem workers disponíveis para emprestar ao master A, tornando o fluxo de negociação
M2M inoperante em modo autônomo.

**Solução:** em `_handle_apresentacao`, quando a fila está vazia **e o worker é local**
(sem `SERVER_UUID`), adicioná-lo a `idle_workers` com seu ID e endereço de peer.
Workers emprestados (com `SERVER_UUID`) não entram em `idle_workers` — eles já são
"temporários" e não devem ser reemprestados.

---

### Bug 5 — Sem canal para enviar `command_redirect` / `command_release`

**Causa:** O worker usa conexões TCP de curta duração — uma por ciclo de tarefa. Não
há conexão persistente pela qual o master possa "empurrar" um comando fora do ciclo.
As funções `handle_command_redirect` e `handle_command_release` existem no worker mas
nunca são chamadas (o `work_loop` não as integra).

A função `_redirect_workers` no master apenas loga — não envia nada de fato.

**Solução em duas partes:**

**5a — Master (filas de comandos pendentes):**
- Adicionar `self.pending_redirects: dict[str, str]` — `{worker_id: new_master_address}`.
- Adicionar `self.pending_releases: dict[str, str]` — `{worker_id: original_master_address}`.
- Em `_handle_apresentacao`, **antes** de servir tarefas:
  1. Se `worker_id` está em `pending_releases` → enviar `command_release` e retornar.
  2. Se fila vazia e `worker_id` está em `pending_redirects` → enviar `command_redirect`
     e retornar.
- `_redirect_workers` passa a popular `pending_redirects` (em vez de só logar).
- `on_release` (callback de normalização) passa a popular `pending_releases` para cada
  worker emprestado e disparar `notify_worker_returned` ao master de origem.

**5b — Worker (`do_one_task` + `work_loop`):**
- Em `do_one_task`, após receber a resposta do master, verificar se é `command_redirect`
  ou `command_release`:
  - `command_redirect` → registrar-se no novo master (via `register_as_temporary`) e
    retornar novo host/porta.
  - `command_release` → extrair endereço de origem e retornar novo host/porta.
- `work_loop` passa a manter estado `(cur_host, cur_port, cur_origin)` e atualizá-lo
  conforme o retorno de `do_one_task`.

**5c — Endereço do master solicitante no `request_help`:**
Para que o master B saiba para qual endereço redirecionar os workers (endereço do
master A), incluir `"master_address": "ip:porta"` no payload de `request_help`. Este
campo é uma extensão pragmática — não conflita com os campos obrigatórios do PDF, que
apenas lista os mínimos, e é ignorado por implementações que não o reconhecem (parsing
tolerante, Nota 31).

## Arquitetura da solução (somente arquivos consolidados)

```
master.py (root)
  ├── CONFIGURAÇÃO RÁPIDA         [Bug 1, 2: constantes corrigidas]
  ├── class Master
  │   ├── __init__                [Bug 3: set_load inicial; Bug 5a: pending_*]
  │   ├── set_load()              [já correto — só precisa ser chamado]
  │   ├── _handle_apresentacao()  [Bug 3, 4, 5a: set_load + idle + pending queues]
  │   ├── _redirect_workers()     [Bug 5a: popula pending_redirects]
  │   ├── _notify_origin_returned() [Bug 5a: NOVO — notifica master B via TCP]
  │   └── m2m_request_help()      [Bug 5c: inclui master_address no payload]
  └── run_server()                [Bug 5a: conecta on_saturation/on_release automáticos]

worker.py (root)
  ├── CONFIGURAÇÃO RÁPIDA         [Bug 1: DEFAULT_DISC_PORT = 5000]
  ├── do_one_task()               [Bug 5b: trata command_redirect/command_release]
  └── work_loop()                 [Bug 5b: mantém e atualiza estado de conexão]
```

## Invariantes preservados

- **Nenhuma alteração nas pastas `sprints/`** — as implementações originais de cada
  sprint ficam intactas para referência e para os testes unitários/integração.
- **Protocolo de fio inalterado** — payloads obrigatórios idênticos ao PDF. O campo
  `master_address` em `request_help` é um campo adicional tolerado (Nota 31).
- **Retro-compatibilidade dos modos** — `--mode heartbeat`, `--mode tasks` e
  `--mode discovery` continuam funcionando exatamente como antes.
- **Sem locks** — asyncio single-thread; todas as operações sobre `pending_redirects`,
  `pending_releases`, `idle_workers` e `borrowed_in` ocorrem sem `await` no meio,
  garantindo atomicidade (Nota 38 do PDF).

## Histerese — valores corretos

```
capacity = 100        (saturação: load > 100 → pede ajuda)
release_threshold = 60 (liberação: load < 60 → devolve workers)
dead zone = [60, 100]  (evita ping-pong)
```

Para testes rápidos em sala de aula, os valores podem ser reduzidos via CLI:
```bash
python master.py --capacity 5 --release-threshold 2 --tasks t1,t2,t3,t4,t5,t6
```

## Diagrama de fluxo corrigido (Sprint 3.1)

```
[Master B] inicia com workers conectados (ociosos em idle_workers)
[Master A] inicia com fila de tarefas > capacity

set_load() → satura → on_saturation(needed) → request_help_to(B)
  A → B : request_help {master_id, master_address, current_load, capacity, workers_needed}
  B → A : response_accepted {worker_details}
  B popula pending_redirects[W1] = "ip_A:porta_A"

[Worker W1 apresenta a B] → B detecta pending_redirects[W1]
  B → W1 : command_redirect {new_master_address: "ip_A:porta_A"}
  W1 → A : register_temporary_worker {worker_id, original_master_address}
  [W1 entra em work_loop(A, origin=B)]
  W1 → A : ALIVE (SERVER_UUID=B) → QUERY → STATUS OK → ACK

[Master A: carga cai] → set_load() → libera → on_release()
  A popula pending_releases[W1] = "ip_B:porta_B"
  A → B : notify_worker_returned {worker_id: W1}

[Worker W1 apresenta a A] → A detecta pending_releases[W1]
  A → W1 : command_release {original_master_address: "ip_B:porta_B"}
  [W1 atualiza work_loop → cur_host=B, cur_port=porta_B, cur_origin=None]
  W1 → B : ALIVE (sem SERVER_UUID) → tarefa normal
```

## Referências

- `plano_proj_SD-26_1.pdf` — Notas 31 (strict parsing), 35 (histerese), 38 (atomicidade)
- Specs anteriores: heartbeat, tarefas-workers, discovery-election, m2m-negociacao
- Plano de implementação: `2026-05-31-m2m-negociacao-implementation.md`
