# Runbook — Canal de Descoberta (Worker ↔ Master)

Este runbook descreve como testar localmente o Canal de Descoberta (UDP multicast/broadcast).

Pré-requisitos
- Python 3.x
- Dependências instaladas no venv: `pytest` (opcional para testes)

Como executar (modo manual)

- Em um terminal, iniciar um Master responder:

```bash
python -c "from src.discovery.master_discovery import MasterResponder; m=MasterResponder(); m.start(); input('Pressione Enter para parar'); m.stop()"
```

- Em outro terminal, executar a descoberta do Worker (mostra respostas):

```bash
python -c "from src.discovery.worker_discovery import discover_masters, perform_discovery_and_election; print(discover_masters(timeout_ms=3000))"
```

- Para executar descoberta seguida de eleição (TCP handshake):

```bash
python -c "from src.discovery.worker_discovery import perform_discovery_and_election; print(perform_discovery_and_election(timeout_ms=3000))"
```

Critérios de sucesso
- O Worker deve imprimir uma lista contendo pelo menos um dicionário com `type == 'discovery_response'` e `master_id` presente.

Rollback
- Reverter o branch/PR se houver regressões: `git checkout main && git revert <commit>` ou simplesmente reverter a PR.

Notas
- Se multicast não funcionar na rede local, use `DISCOVERY_MODE=broadcast` ao executar `discover_masters`.
- Testes automatizados são fornecidos em `tests/` — execute `pytest` para validar.
 - Testes automatizados são fornecidos em `tests/` — execute `pytest` para validar.
 - O Master responder agora abre um servidor TCP (padrão `50010`) usado para o handshake de eleição. Configure `tcp_port` ao iniciar `MasterResponder` para testes locais alternativos.
