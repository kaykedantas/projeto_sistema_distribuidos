"""
master.py — Ponto de entrada do Nó Master (Sprint 01: Heartbeat).

Executa o servidor assíncrono de Heartbeat. A lógica vive em
``src/heartbeat/master_async.py``; este arquivo apenas garante que a raiz do
projeto esteja no ``sys.path`` e delega para o ``main()`` do módulo.

Uso:
    python master.py --host 0.0.0.0 --port 10000 --id MASTER_KAYKE
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.heartbeat.master_async import main

if __name__ == "__main__":
    main()
