"""Configuração compartilhada dos testes: garante que a raiz do projeto
esteja em ``sys.path`` para que ``import src.heartbeat...`` funcione tanto
sob pytest quanto pelo runner standalone (run_tests.py)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
