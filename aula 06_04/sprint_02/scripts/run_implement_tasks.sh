#!/usr/bin/env bash
set -euo pipefail

echo "Implementando Tarefas 01-03 (discovery, election, handshake) em modo script..."

ROOT_DIR="$(pwd)"

# Detectar python
PY_CMD=""
if command -v python3 >/dev/null 2>&1; then
  PY_CMD=python3
elif command -v python >/dev/null 2>&1; then
  PY_CMD=python
else
  echo "Python não encontrado. Instale Python 3.x e reexecute." >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git não encontrado. Instale git e reexecute." >&2
  exit 1
fi

echo "Usando Python: $PY_CMD"

# Verifica pytest
if ! $PY_CMD -m pytest --version >/dev/null 2>&1; then
  echo "pytest não encontrado, instalando via pip (usuário)..."
  if command -v pip >/dev/null 2>&1; then
    PIP_CMD=pip
  elif command -v pip3 >/dev/null 2>&1; then
    PIP_CMD=pip3
  else
    echo "pip não encontrado; instale pip ou pytest manualmente." >&2
    exit 1
  fi
  $PIP_CMD install --user pytest
fi

mkdir -p src tests
touch src/__init__.py

echo "--- Task 1: Discovery (TDD) ---"

cat > tests/test_discovery.py <<'PY'
import json
from src.discovery import make_discovery_payload, parse_discovery_reply

def test_make_discovery_payload_contains_type():
    p = make_discovery_payload("W-101")
    assert b'DISCOVERY' in p

def test_parse_discovery_reply_valid():
    raw = b'{"TYPE":"DISCOVERY_REPLY","MASTER_NAME":"MASTER_1","MASTER_IP":"192.168.1.20","MASTER_PORT":6000,"STATUS":"AVAILABLE"}'
    obj = parse_discovery_reply(raw)
    assert obj['MASTER_NAME'] == 'MASTER_1'
PY

echo "Executando pytest (esperado: falha porque src/discovery.py não existe ainda)"
if $PY_CMD -m pytest tests/test_discovery.py -q; then
  echo "Nota: o teste PASSOU inesperadamente (talvez os arquivos já existam). Continuando."
else
  echo "Teste falhou como esperado; agora criando implementação mínima..."
fi

cat > src/discovery.py <<'PY'
import json

def make_discovery_payload(worker_uuid: str) -> bytes:
    return json.dumps({"TYPE": "DISCOVERY", "WORKER_UUID": worker_uuid}).encode('utf-8')

def parse_discovery_reply(raw: bytes) -> dict:
    d = json.loads(raw.decode('utf-8'))
    if d.get('TYPE') != 'DISCOVERY_REPLY':
        raise ValueError('invalid type')
    required = ['MASTER_NAME', 'MASTER_IP', 'MASTER_PORT']
    for k in required:
        if k not in d:
            raise ValueError(f'missing {k}')
    return d
PY

echo "Rodando pytest para Task 1"
$PY_CMD -m pytest tests/test_discovery.py -q

echo "Comitando mudanças: discovery"
git add src/discovery.py tests/test_discovery.py
git commit -m "feat(discovery): add discovery payload and parser tests" || echo "Commit falhou (verifique git config)"

echo "--- Task 2: Election (TDD) ---"

cat > tests/test_election.py <<'PY'
from src.election import elect_master

def test_elect_master_lexicographic():
    replies = [
        {"MASTER_NAME":"MASTER_2","MASTER_IP":"10.0.0.2"},
        {"MASTER_NAME":"MASTER_1","MASTER_IP":"10.0.0.1"},
    ]
    winner = elect_master(replies)
    assert winner['MASTER_NAME'] == 'MASTER_1'
PY

echo "Executando pytest (esperado: falha porque src/election.py não existe ainda)"
if $PY_CMD -m pytest tests/test_election.py -q; then
  echo "Nota: o teste PASSOU inesperadamente (talvez os arquivos já existam). Continuando."
else
  echo "Teste falhou como esperado; agora criando implementação mínima..."
fi

cat > src/election.py <<'PY'
from typing import List, Dict, Optional

def elect_master(replies: List[Dict]) -> Optional[Dict]:
    if not replies:
        return None
    sorted_replies = sorted(replies, key=lambda r: (r.get('MASTER_NAME',''), r.get('MASTER_IP','')))
    return sorted_replies[0]
PY

echo "Rodando pytest para Task 2"
$PY_CMD -m pytest tests/test_election.py -q

echo "Comitando mudanças: election"
git add src/election.py tests/test_election.py
git commit -m "feat(election): deterministic master election and tests" || echo "Commit falhou (verifique git config)"

echo "--- Task 3: Handshake (TDD) ---"

cat > tests/test_handshake.py <<'PY'
from unittest.mock import MagicMock, patch
from src.handshake import perform_handshake

def test_perform_handshake_accept():
    fake_sock = MagicMock()
    fake_sock.recv.return_value = b'{"TYPE":"ELECTION_ACK","STATUS":"ACCEPTED","MASTER_NAME":"MASTER_1"}'
    with patch('socket.create_connection', return_value=fake_sock):
        ok = perform_handshake('127.0.0.1', 6000, 'W-101', 'MASTER_1')
        assert ok is True
PY

echo "Executando pytest (esperado: falha porque src/handshake.py não existe ainda)"
if $PY_CMD -m pytest tests/test_handshake.py -q; then
  echo "Nota: o teste PASSOU inesperadamente (talvez os arquivos já existam). Continuando."
else
  echo "Teste falhou como esperado; agora criando implementação mínima..."
fi

cat > src/handshake.py <<'PY'
import socket
import json
from typing import Optional

def perform_handshake(master_ip: str, master_port: int, worker_uuid: str, master_name: str, timeout: float = 5.0) -> bool:
    s = socket.create_connection((master_ip, master_port), timeout)
    try:
        payload = json.dumps({"TYPE": "ELECTION_ACK", "WORKER_UUID": worker_uuid, "SELECTED_MASTER": master_name}).encode('utf-8')
        s.send(payload)
        resp = s.recv(4096)
        d = json.loads(resp.decode('utf-8'))
        return d.get('TYPE') == 'ELECTION_ACK' and d.get('STATUS') == 'ACCEPTED'
    finally:
        try:
            s.close()
        except Exception:
            pass
PY

echo "Rodando pytest para Task 3"
$PY_CMD -m pytest tests/test_handshake.py -q

echo "Comitando mudanças: handshake"
git add src/handshake.py tests/test_handshake.py
git commit -m "feat(handshake): add TCP handshake and tests" || echo "Commit falhou (verifique git config)"

echo "--- Execução completa: rodando todos os testes ---"
$PY_CMD -m pytest -q || { echo "Alguns testes falharam."; exit 1; }

echo "Todos os testes passaram com sucesso."

echo "Arquivos criados/atualizados:"
git --no-pager status --porcelain || true

echo "Script finalizado com sucesso."
