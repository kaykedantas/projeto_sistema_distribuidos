# Sprint 2.1 — Descoberta Dinâmica e Eleição de Master pelos Workers

O Worker passa a iniciar **sem IP/porta do Master configurados**: ele descobre
Masters na rede via **UDP** (broadcast por padrão), elege um de forma
**determinística** pelo nome, faz a transição para **TCP**, confirma a eleição
(`ELECTION_ACK` -> `ACCEPTED`) e então inicia o ciclo de Heartbeat (Sprint 01) e
de tarefas (Sprint 02). Esta pasta é **cumulativa** (Sprint 01 + 02 + 2.1).

## Estrutura

```
master.py                      # Master: descoberta UDP + TCP (tarefas/heartbeat)
worker.py                      # Worker: descoberta -> eleicao -> TCP -> heartbeat
src/heartbeat/
  messaging.py                 # JSON + \n (reaproveitado)
  discovery.py                 # NOVO: eleicao deterministica + transporte UDP
  master_async.py              # + responder UDP + ELECTION_ACK
  worker_async.py              # + bootstrap (discover/elect/connect/confirm)
tests/                         # 33 testes (sprints 01, 02 e 2.1)
scripts/run_discovery_demo.py  # demo automatica (descoberta -> heartbeat)
run_tests.py                   # runner SEM dependencias
```

## Payloads oficiais (do discovery.pdf — terminam com \n, controle em CAIXA ALTA)

| # | Direcao | Payload |
|---|---------|---------|
| 1 | Worker -> UDP (broadcast/multicast) | `{"TYPE":"DISCOVERY","WORKER_UUID":"W-101"}` |
| 2 | Master -> Worker (unicast UDP) | `{"TYPE":"DISCOVERY_REPLY","MASTER_NAME":"MASTER_1","MASTER_IP":"...","MASTER_PORT":10000,"STATUS":"AVAILABLE"}` |
| 3 | Worker -> Master (TCP) | `{"TYPE":"ELECTION_ACK","WORKER_UUID":"W-101","SELECTED_MASTER":"MASTER_1"}` |
| 4 | Master -> Worker (TCP) | `{"TYPE":"ELECTION_ACK","STATUS":"ACCEPTED","MASTER_NAME":"MASTER_1"}` |

Apos o `ACCEPTED`, o Worker inicia imediatamente o ciclo de Heartbeat.

## Regra de eleicao (deterministica)

Menor `MASTER_NAME` em ordenacao **natural**: `MASTER_1 < MASTER_2 < MASTER_10`
(o numero e comparado como numero, nao como texto). Todos os Workers que recebem
o mesmo conjunto de respostas elegem o mesmo Master, sem se comunicarem.

## Como executar — uma maquina (localhost)

```bash
# Terminal 1 — Master
python master.py --name MASTER_1 --port 10000 --disc-port 5000 --advertise-ip 127.0.0.1 --tasks Michel,Julia

# Terminal 2 — Worker (descobre sozinho; nao recebe IP/porta do Master)
python worker.py --uuid W-101 --discovery-mode broadcast --disc-port 5000
```

## Como executar — varias maquinas na mesma LAN (receita de teste)

Pre-requisitos: maquinas na **mesma sub-rede**; liberar a **porta UDP 5000** e a
**porta TCP** do Master no firewall.

```bash
# Maquina A (Master 1):
python master.py --name MASTER_1 --port 10000 --disc-port 5000
#   (o IP anunciado e autodetectado; force com --advertise-ip <IP_LAN> se houver
#    multiplas interfaces/VPN)

# Maquina B (Master 2) — opcional, para exercitar a eleicao (CT02):
python master.py --name MASTER_2 --port 10000 --disc-port 5000

# Maquina C (Worker), mesma sub-rede:
python worker.py --uuid W-101 --discovery-mode broadcast --disc-port 5000
#   Esperado nos logs: DISCOVERY -> ELECTION (elege MASTER_1) -> CONNECTING ->
#   "Eleicao confirmada por MASTER_1" -> Heartbeat/QUERY.
```

Rode **dois Workers ao mesmo tempo** (em maquinas diferentes): ambos devem
eleger **MASTER_1** de forma independente (DoD 3).

> **Broadcast vs multicast.** O padrao e **broadcast** (`255.255.255.255:5000`),
> que costuma ser mais robusto em LAN/WiFi de sala de aula. Para usar multicast
> (`239.255.255.250`), passe `--discovery-mode multicast` no Worker. Se a sua
> rede bloquear broadcast, tente multicast (e vice-versa). Broadcast nao cruza
> sub-redes/roteadores — todos devem estar no mesmo segmento.

## Testes

```bash
python run_tests.py          # 33 testes (sem dependencias): sprints 01, 02 e 2.1
# ou, com pytest:
pip install -r requirements.txt && pytest -q
```

> **Nota sobre o ambiente de teste.** Os testes automatizados exercitam o UDP em
> **loopback** (unicast para `127.0.0.1`), cobrindo todo o codigo de descoberta,
> eleicao e handshake. O comportamento de **broadcast/multicast entre maquinas**
> deve ser validado na LAN com a receita acima.

## Modos legados

O Worker mantem os modos das sprints anteriores para alvo fixo (sem descoberta):
`--mode tasks --host <ip> --port <porta>` e `--mode heartbeat`. O padrao e
`--mode discovery` (Sprint 2.1).

## Definicao de "Pronto" (DoD) — Sprint 2.1

- [x] **1.** Worker inicia sem IP/porta do Master configurados.
- [x] **2.** Faz descoberta via rede e lista os Masters respondentes.
- [x] **3.** Elege consistentemente o mesmo Master que outros Workers simultaneos.
- [x] **4.** Estabelece TCP com o eleito e envia o primeiro Heartbeat com sucesso.
- [x] **5.** Trata timeout, ausencia de Masters (NO_MASTER_FOUND + backoff) e
  queda pos-eleicao (invalida cache e reinicia).
- [x] **6.** Todos os payloads em JSON + \n com parsing estrito.

Casos de teste cobertos: **CT01** (um Master -> conecta, e2e), **CT02** (elege
MASTER_1 entre varios), **CT03** (sem respostas -> vazio -> fallback), **CT04**
(queda pos-eleicao detectada), **CT05** (reply sem MASTER_PORT -> descartada).
