import threading
import time
from src.discovery.worker_discovery import perform_discovery_and_election
from src.discovery.master_discovery import MasterResponder


def run_master_for(duration_s=4, group='239.255.0.1', port=50000, tcp_port=50011, mode='multicast', master_name=None):
    m = MasterResponder(group=group, port=port, mode=mode, tcp_port=tcp_port, master_name=master_name)
    m.start()
    try:
        time.sleep(duration_s)
    finally:
        m.stop()


def test_discovery_and_election_tcp():
    master_name = 'MASTER_TEST_1'
    t = threading.Thread(target=run_master_for, kwargs={'duration_s': 3, 'tcp_port': 50011, 'master_name': master_name}, daemon=True)
    t.start()
    time.sleep(0.2)
    result = perform_discovery_and_election(timeout_ms=3000, group='239.255.0.1', port=50000, mode='multicast')
    assert result is not None, "Election handshake failed or no masters found"
    assert result.get('selected_name') == master_name
