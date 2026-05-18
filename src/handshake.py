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
