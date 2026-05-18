# Tarefa 01 — Canal de Descoberta (UDP Multicast / Broadcast)

Resumo
-------
Implementar mecanismo de descoberta em rede para que Workers encontrem Masters automaticamente sem configuração manual de IP/porta.

Objetivo
--------
Ao iniciar, cada Worker envia um pacote de descoberta via UDP (multicast ou broadcast). Masters escutam no mesmo grupo/porta e respondem via UDP unicast para o IP/porta de origem do Worker, informando nome, IP, porta e status.

Requisitos Funcionais
---------------------
- Endereço e porta: usar UDP Multicast (por exemplo `239.255.255.250`) ou Broadcast (`255.255.255.255`) em porta dedicada (ex.: `5000`). Deve ser configurável.
- Worker:
  - Ao iniciar, enviar mensagem JSON de descoberta para o endereço/porta configurados.
  - Coletar respostas por um `discovery_timeout` configurável (padrão: `3000 ms`).
  - Registrar cada resposta (MASTER_NAME, MASTER_IP, MASTER_PORT, STATUS, timestamp).
  - Ignorar respostas malformadas; registrar warning.
- Master:
  - Escutar no mesmo grupo/porta e responder via UDP unicast ao IP/porta de origem do Worker.
  - Resposta deve conter nome do Master, IP, porta TCP para conexão e status.
- Retries e backoff: se nenhum Master responder, aplicar backoff exponencial e repetir descoberta.
- Strict parsing: rejeitar mensagens com campos faltantes ou tipos incorretos.

Payloads (exemplos)
-------------------
Discovery (Worker -> multicast/broadcast UDP):

```json
{"TYPE":"DISCOVERY","WORKER_UUID":"W-101"}
```

Discovery Reply (Master -> Worker unicast UDP):

```json
{
  "TYPE": "DISCOVERY_REPLY",
  "MASTER_NAME": "MASTER_1",
  "MASTER_IP": "192.168.1.20",
  "MASTER_PORT": 6000,
  "STATUS": "AVAILABLE"
}
```

Timeout e coleta
----------------
- Default `discovery_timeout`: 3000 ms (exemplo).
- Worker coleta todas as respostas recebidas dentro do timeout e então segue para a etapa de eleição.

Critérios de Aceitação
----------------------
- CT01 (único Master disponível): Worker envia DISCOVERY e recebe DISCOVERY_REPLY; Worker inicia conexão TCP com o Master selecionado e entra no ciclo de Heartbeat.
- CT02 (múltiplos Masters): Worker coleta múltiplas respostas e passa para a etapa de eleição (Tarefa 02).
- CT03 (nenhum Master responde): Worker registra `NO_MASTER_FOUND`, aplica backoff e repete descoberta.

Notas de implementação
---------------------
- Validar JSON estritamente e logar mensagens com nível apropriado (info/warn/error).
- Não alterar o estado global até que exista confirmação via TCP (handshake) com o Master eleito.
- Todos os valores configuráveis (endereço, porta, timeout, backoff) devem ficar em arquivo de configuração ou variáveis de ambiente.
