import threading
import time
from src.discovery.worker_discovery import discover_masters
from src.discovery.master_discovery import MasterResponder


def run_master_for(duration_s=3, group='239.255.0.1', port=50000, mode='multicast'):
    m = MasterResponder(group=group, port=port, mode=mode)
    m.start()
    try:
        time.sleep(duration_s)
    finally:
        m.stop()


def test_worker_discovers_master():
    t = threading.Thread(target=run_master_for, kwargs={'duration_s': 2}, daemon=True)
    t.start()
    time.sleep(0.2)
    responses = discover_masters(timeout_ms=2000, group='239.255.0.1', port=50000, mode='multicast')
    if not responses:
        # fallback to broadcast if multicast didn't work in this environment
        responses = discover_masters(timeout_ms=2000, group='239.255.0.1', port=50000, mode='broadcast')
    assert isinstance(responses, list)
    assert any(r.get('type') == 'discovery_response' and r.get('master_id') for r in responses)
