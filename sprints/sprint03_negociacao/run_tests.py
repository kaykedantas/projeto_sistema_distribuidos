#!/usr/bin/env python3
"""
run_tests.py — Runner de testes SEM dependências externas.

Útil quando o ambiente não tem pytest instalado. Descobre funções ``test_*``
nos módulos de ``tests/`` e executa cada uma, reportando PASS/FAIL.

Na sua máquina, o ideal é usar pytest:

    pip install pytest
    pytest -q

Mas ``python run_tests.py`` produz o mesmo veredito sem instalar nada.
"""

import importlib
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

TEST_MODULES = [
    "tests.test_messaging",
    "tests.test_master_worker_integration",
    "tests.test_messaging_sprint02",
    "tests.test_worker_unit",
    "tests.test_tarefas_integration",
    "tests.test_discovery_logic",
    "tests.test_discovery_udp",
    "tests.test_master_discovery",
    "tests.test_worker_bootstrap",
    "tests.test_discovery_e2e",
    "tests.test_m2m",
    "tests.test_load_state",
    "tests.test_negociacao",
    "tests.test_redirect_register",
    "tests.test_devolucao",
    "tests.test_resiliencia_m2m",
    "tests.test_m2m_e2e",
]


def main() -> int:
    total = passed = 0
    falhas = []

    for modname in TEST_MODULES:
        module = importlib.import_module(modname)
        for name in sorted(dir(module)):
            if not name.startswith("test_"):
                continue
            fn = getattr(module, name)
            if not callable(fn):
                continue
            total += 1
            ident = f"{modname}::{name}"
            try:
                fn()
                passed += 1
                print(f"PASS  {ident}")
            except Exception:  # noqa: BLE001
                falhas.append(ident)
                print(f"FAIL  {ident}")
                traceback.print_exc()

    print("\n" + "=" * 50)
    print(f"Resultado: {passed}/{total} testes passaram")
    if falhas:
        print("Falharam: " + ", ".join(falhas))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
