# Sprint 01 — Mecanismo de Heartbeat (Worker ↔ Master)

Estabelece a comunicação base entre **Worker** e **Master**: o Worker verifica
periodicamente se o seu "mestre" está ativo, trocando mensagens JSON via TCP
(delimitadas por `\n`).

## Estrutura

```
master.py                      # entry point do Master  (python master.py)
worker.py                      # entry point do Worker  (python worker.py)
src/heartbeat/
  messaging.py                 # (de)serialização JSON + helpers \n
  master_async.py              # servidor asyncio (responde ALIVE)
  worker_async.py              # cliente asyncio (envia HEARTBEAT a cada 10s)
tests/
  test_messaging.py            # testes de unidade
  test_master_worker_integration.py  # testes de integração (TCP real)
scripts/run_heartbeat_demo.py  # demo automática (Master + 3 heartbeats)
run_tests.py                   # runner de testes SEM dependências
```

## Payloads oficiais (do plano do projeto)

Envio — Worker → Master:

```json
{ "SERVER_UUID": "MASTER_KAYKE", "TASK": "HEARTBEAT" }
```

Resposta — Master → Worker:

```json
{ "SERVER_UUID": "MASTER_KAYKE", "TASK": "HEARTBEAT", "RESPONSE": "ALIVE" }
```

Parâmetros: intervalo de heartbeat = **10s**; timeout de resposta = **5s**.

## Como executar

Em um terminal, suba o Master:

```bash
python master.py --host 0.0.0.0 --port 10000 --id MASTER_KAYKE
```

Em outro terminal, rode o Worker:

```bash
python worker.py --host 127.0.0.1 --port 10000 --master MASTER_KAYKE
```

Saída esperada no Worker (a cada 10s):

```
[worker] INFO: HEARTBEAT enviado para 127.0.0.1:10000
[worker] INFO: Master MASTER_KAYKE respondeu ALIVE
```

Demo rápida em um único comando:

```bash
python scripts/run_heartbeat_demo.py
```

## Testes

Com pytest (recomendado):

```bash
pip install -r requirements.txt
pytest -q
```

Sem instalar nada (runner standalone):

```bash
python run_tests.py
```

## Definição de "Pronto" (DoD) — Sprint 01

- [x] **1.** O Worker abre uma conexão TCP com o Master.
- [x] **2.** O Master recebe o JSON, faz o *parsing* e identifica o comando `HEARTBEAT`.
- [x] **3.** O Worker recebe a confirmação `ALIVE` e a imprime no log.
- [x] **4.** A conexão é mantida/reestabelecida sem travar os processos
  (timeout de 5s + reconexão com backoff exponencial).

## Notas de implementação

- **Delimitador:** toda mensagem termina com `\n` (enquadramento no stream TCP).
- **Strict parsing:** campos desconhecidos são ignorados; ausência do campo
  obrigatório `TASK` é logada sem derrubar o processo.
- **Concorrência:** o Master usa `asyncio`, atendendo vários Workers sem bloquear
  — base para as Sprints 02 e 03.
- **Produção sem dependências externas:** o código usa só a biblioteca padrão;
  `pytest`/`pytest-asyncio` são necessários apenas para os testes.
