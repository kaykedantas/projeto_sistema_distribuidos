# Tarefa 02 — Lógica de Eleição Determinística

Resumo
-------
Após coletar respostas de Masters, o Worker deve escolher determinística e consistentemente um Master eleito entre os candidatos recebidos.

Objetivo
--------
Garantir que, dado o mesmo conjunto de respostas, todos os Workers aplicando a mesma regra selecionem o mesmo Master eleito (consenso baseado em regras determinísticas simples).

Regra de Eleição (recomendada)
------------------------------
- Ordenar os Masters por `MASTER_NAME` em ordem lexicográfica crescente; o primeiro da lista é o `selected_master`.
- Observação prática: exemplos de nomes como `MASTER_1`, `MASTER_2`, `MASTER_10` seguem ordenação lexicográfica padrão ("MASTER_1" < "MASTER_10" < "MASTER_2").
- Se ocorrer duplicação exata de `MASTER_NAME`, use como critério secundário `MASTER_IP` (lexicográfico). Documentar esse critério.

Fluxo
-----
1. Worker espera o `discovery_timeout` e coleta todas as `DISCOVERY_REPLY` válidas.
2. Aplica a função de ordenação e escolhe o primeiro elemento como `selected_master`.
3. Grava `selected_master` em estado local transitório e tenta abrir conexão TCP (Tarefa 03).

Requisitos Não-Funcionais
-------------------------
- Determinismo: a função de ordenação deve depender apenas dos campos da resposta (`MASTER_NAME`,`MASTER_IP`,...), sem usar timestamps ou ordem de chegada.
- Observabilidade: registrar lista completa de candidatos antes e depois da ordenação (para auditoria/replay).

Critérios de Aceitação
----------------------
- CT02: Dado um conjunto de respostas contendo `MASTER_1`, `MASTER_2`, `MASTER_3`, todos os Workers elegem `MASTER_1` (menor lexicograficamente).
- Consistência: se dois Workers receberem o mesmo conjunto de respostas (mesmos valores), ambos elegem o mesmo Master.

Pseudo-código (exemplo)
------------------------
```python
def elect_master(replies):
    # replies: lista de dicionários com keys MASTER_NAME, MASTER_IP, MASTER_PORT
    sorted_replies = sorted(replies, key=lambda r: (r['MASTER_NAME'], r['MASTER_IP']))
    return sorted_replies[0]
```

Notas
-----
- Não implementar mecanismos de eleição distribuída complexos (p. ex. Raft) — a exigência pedagógica é uma eleição determinística simples.
- Documentar claramente a regra em `docs/` para evitar divergências futuras.
