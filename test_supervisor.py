"""
test_supervisor.py — Testes da Sprint 4 (Supervisor de Métricas) no master.py raiz.

Rode com:  python test_supervisor.py   (sem instalar nada — psutil é mockado)
"""
import asyncio
import contextlib
import time
from collections import deque

import master as M


# ── Task 2: helpers de fila com timestamps ───────────────────────────

def test_oldest_task_age_cresce_e_zera():
    m = M.Master("127.0.0.1", 0, master_id="MASTER_9", tasks=["T1"])
    # força o timestamp da T1 para 5s atrás
    m.task_times[0] = time.time() - 5
    assert m.oldest_task_age_s() >= 5
    # ao consumir a única tarefa, idade volta a 0
    assert m._dequeue() == "T1"
    assert m.oldest_task_age_s() == 0


def test_enqueue_front_mantem_sincronia():
    m = M.Master("127.0.0.1", 0, master_id="MASTER_9", tasks=[])
    m._enqueue("A")
    m._enqueue("B")
    m._enqueue_front("C")              # C vai para a frente (reenfileiramento)
    assert list(m.tasks) == ["C", "A", "B"]
    assert len(m.task_times) == 3      # deque de tempos permanece alinhada


# ── Task 3: contadores tasks_completed / tasks_failed ────────────────

async def _sobe(m):
    server = await asyncio.start_server(m.handle_client, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def _ciclo_status(port, status):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    await M.send_message(writer, {"WORKER": "ALIVE", "WORKER_UUID": "W1"})
    await asyncio.wait_for(M.read_message(reader), timeout=2)         # QUERY
    await M.send_message(writer, {"STATUS": status, "TASK": "QUERY", "WORKER_UUID": "W1"})
    await asyncio.wait_for(M.read_message(reader), timeout=2)         # ACK
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()


def test_contadores_ok_e_nok():
    async def cenario():
        m = M.Master("127.0.0.1", 0, master_id="MASTER_9", tasks=["T1", "T2"],
                     max_task_attempts=5)
        server, port = await _sobe(m)
        await _ciclo_status(port, "OK")
        await _ciclo_status(port, "NOK")
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
        return m
    m = asyncio.run(cenario())
    assert m.tasks_completed == 1, m.tasks_completed
    assert m.tasks_failed == 1, m.tasks_failed


# ── Task 4/5: psutil mockado + métricas de sistema ───────────────────

class _FakePsutil:
    def virtual_memory(self):
        class V: total = 16 * 1024**3; available = 8 * 1024**3; percent = 50.0
        return V()
    def disk_usage(self, _):
        class D: total = 512 * 1024**3; free = 256 * 1024**3; percent = 50.0
        return D()
    def getloadavg(self): return (1.0, 2.0, 3.0)
    def cpu_percent(self): return 42.5
    def cpu_count(self, logical=True): return 8 if logical else 4


def test_collect_system_metrics():
    orig = M.psutil
    M.psutil = _FakePsutil()
    try:
        s = M._collect_system_metrics(time.time() - 100)
    finally:
        M.psutil = orig
    assert s["uptime_seconds"] >= 100
    assert s["cpu"] == {"usage_percent": 42.5, "count_logical": 8, "count_physical": 4}
    assert s["memory"]["total_mb"] == 16384
    assert s["memory"]["memory_used"] == 8192
    assert s["disk"]["total_gb"] == 512.0
    assert s["load_average_1m"] == 1.0 and s["load_average_5m"] == 2.0


def test_build_performance_report_estrutura_e_mapeamento():
    m = M.Master("127.0.0.1", 0, master_id="MASTER_9", tasks=["T1", "T2"])
    m.supervisor_uuid = "michel_1"
    m.workers = {"W1": {"emprestado": False, "origem": None, "concluidas": 0}}
    m.idle_workers = [{"id": "W1", "address": "ip:1"}]
    m.in_flight = {"W2": "T9"}
    m.lent_out = {"W3": {"para": "MASTER_B"}}
    m.borrowed_in = {"W4": {"origem": "10.0.0.2:7011"}}
    m.tasks_completed, m.tasks_failed = 7, 2
    m.neighbors = {"MASTER_B": ("10.0.0.2", 7011)}

    orig = M.psutil
    M.psutil = _FakePsutil()
    try:
        p = M.build_performance_report(m, neighbor_status={"MASTER_B": True})
    finally:
        M.psutil = orig

    assert p["server_uuid"] == "michel_1"
    assert p["role"] == "master" and p["task"] == "performance_report"
    assert p["payload_version"] == "sprint4-monitor"
    assert p["timestamp"].endswith("Z")
    fs = p["performance"]["farm_state"]
    assert fs["workers"]["total_registered"] == 1
    assert fs["workers"]["workers_idle"] == 1
    assert fs["workers"]["workers_borrowed"] == 1     # lent_out
    assert fs["workers"]["workers_received"] == 1     # borrowed_in
    assert fs["workers"]["workers_utilization"] == 1  # in_flight
    assert {"direction": "out", "peer_uuid": "MASTER_B"} in fs["workers"]["borrowed_workers"]
    assert fs["tasks"]["tasks_pending"] == 2
    assert fs["tasks"]["tasks_completed"] == 7 and fs["tasks"]["tasks_failed"] == 2
    ct = p["performance"]["config_thresholds"]
    assert ct["max_task"] == m.capacity and ct["release_task"] == m.release_threshold
    nb = p["performance"]["neighbors"][0]
    assert nb["server_uuid"] == "MASTER_B" and nb["status"] == "available"


# ── Task 6: sender TLS resiliente ────────────────────────────────────

def test_send_report_tls_engole_falha():
    async def cenario():
        # porta 1 fechada -> conexão falha; a função NÃO pode lançar
        await M.send_report_tls({"x": 1}, "127.0.0.1", 1, timeout=1.0)
        return True
    assert asyncio.run(cenario()) is True


# ── runner ───────────────────────────────────────────────────────────

TESTS = [
    test_oldest_task_age_cresce_e_zera,
    test_enqueue_front_mantem_sincronia,
    test_contadores_ok_e_nok,
    test_collect_system_metrics,
    test_build_performance_report_estrutura_e_mapeamento,
    test_send_report_tls_engole_falha,
]


def main():
    import logging
    logging.disable(logging.CRITICAL)
    passed = 0
    for t in TESTS:
        try:
            if asyncio.iscoroutinefunction(t):
                asyncio.run(t())
            else:
                t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL  {t.__name__}: {e!r}")
    print("=" * 50)
    print(f"Resultado: {passed}/{len(TESTS)} testes passaram")
    raise SystemExit(0 if passed == len(TESTS) else 1)


if __name__ == "__main__":
    main()
