# Heartbeat Mechanism — Design

Date: 2026-05-30

Resumo
- Objetivo: implementar o mecanismo de Heartbeat entre `Worker` e `Master` conforme payload oficial do plano, garantindo que um Worker consiga verificar se seu Master está ativo via JSON sobre TCP (delimitador `\n`).
- Intervalo escolhido: 10s (padrão recomendado pelo usuário).
- Timeout de resposta: 5s.

Requisitos funcionais (extraídos do `plano_proj_SD-26_1.pdf`)
- Worker deve enviar periodicamente o payload de HEARTBEAT ao seu Master.
- Master deve receber, parsear o JSON e responder imediatamente com um payload ALIVE.
- Mensagens JSON devem sempre terminar com `\n` (delimitador de mensagem em stream TCP).
- Worker deve aguardar no máximo 5 segundos pela resposta; em timeout, deverá tentar reconectar.

Payloads oficiais (exatos do PDF)
- HEARTBEAT (Worker → Master)

```json
{
  "SERVER_UUID": "MASTER_KAYKE",
  "TASK": "HEARTBEAT"
}
```

- HEARTBEAT response (Master → Worker)

```json
{
  "SERVER_UUID": "MASTER_KAYKE",
  "TASK": "HEARTBEAT",
  "RESPONSE": "ALIVE"
}
```

Arquitetura proposta
- Abordagem: `asyncio` TCP server/client (Recomendado — abordagem A2).
- Componentes:
  - `messaging` (serialização/deserialização JSON + helpers `read_message` / `send_message` que usam `\n`).
  - `master_async` (servidor asyncio): aceita conexões de Workers e Masters; cada conexão é tratada por uma coroutine que consome mensagens e responde.
  - `worker_async` (cliente asyncio): loop que conecta ao Master, envia HEARTBEAT a cada 10s, aguarda resposta com timeout de 5s, reconecta em caso de erro.
  - Observabilidade: logs por mensagem (request_id quando aplicável), contadores de heartbeats recebidos/timeouts.

Fluxo de dados (simplificado)
1. `Worker` abre conexão TCP com `Master` (se não estiver aberta).
2. `Worker` envia JSON HEARTBEAT terminado por `\n`.
3. `Master` lê até `\n`, faz `json.loads`, identifica `TASK == "HEARTBEAT"` e envia resposta ALIVE (com `RESPONSE: "ALIVE"`).
4. `Worker` lê resposta; se `RESPONSE == "ALIVE"` loga e espera próximo intervalo; em timeout/reconexão tenta reconnect/backoff.

Erros, Resiliência e Robustez
- Parsing: `Master` ignora campos desconhecidos e valida presença de campos obrigatórios; caso campos obrigatórios ausentes -> log de erro + resposta de falha (ou fechamento controlado).
- Timeout: `Worker` usa `asyncio.wait_for(read_message(reader), timeout=5)`; em `TimeoutError` considera conexão perdida e tenta reconectar com backoff exponencial curto (ex.: 1s, 2s, 4s, cap 8s).
- Conexões: `Master` deve suportar múltiplas conexões simultâneas (coroutines por cliente); recursos compartilhados (filas/registro de workers) devem ser protegidos com locks quando necessário.

Testes e DoD (critérios de aceite)
- Unidade: parser/serializer JSON (`messaging`) roundtrip.
- Integração: `Worker` conecta ao `Master`, envia HEARTBEAT, e recebe `ALIVE` (impressão de log). Timeout test (Master não responde, Worker detecta timeout e tenta reconectar).
- DoD (aceitação final): reproduz os itens 1–4 do DoD do PDF para Sprint Heartbeat: conexão TCP aberta; Master parseia HEARTBEAT; Worker recebe `ALIVE` e loga; reconexões funcionam sem travar os processos.

Observações e decisões
- Intervalo de Heartbeat: 10s (escolha do usuário). Timeout: 5s (do plano).
- Protocolo: manter JSON sobre TCP com `\n` delimitador (compatível com restante do projeto e com Sprints 02/03).
- Implementação inicial usará `asyncio` e funções auxiliares para facilitar testes (uma versão mínima `run_once` será adicionada ao `Worker` para testes de integração).

Próximos passos
1. Gerar documento de implementação (plan.md) com passos TDD e arquivos a criar — já solicitado e será gerado.
2. Implementar `messaging`, `master_async`, `worker_async` e testes de integração seguindo o plano.

Arquivos de referência
- Plano original: `plano_proj_SD-26_1.pdf` (payloads e backlog usados como fonte de verdade)

```text
Fonte: plano_proj_SD-26_1.pdf — seção "PAYLOAD OFICIAL" e backlog Sprint Heartbeat.
```
