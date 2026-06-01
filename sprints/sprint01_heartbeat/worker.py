"""
worker.py — Ponto de entrada do Nó Worker (Sprint 01: Heartbeat).

Autor: Kayke Andrade Dantas

Envia HEARTBEAT ao Master em intervalos regulares (10s) e registra a resposta
ALIVE. A lógica vive em ``src/heartbeat/worker_async.py``; este arquivo apenas
ajusta o ``sys.path`` e delega para o ``main()`` do módulo.

Uso:
    python worker.py --host 127.0.0.1 --port 10000 --master MASTER_KAYKE
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.heartbeat.worker_async import main

if __name__ == "__main__":
    main()
