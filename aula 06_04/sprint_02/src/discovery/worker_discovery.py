import json
import socket
import uuid


def make_discovery_message(worker_id=None, hostname=None, reply_port=None):
    payload = {
        'type': 'discovery',
        'version': 1,
        'worker_id': worker_id or str(uuid.uuid4()),
        'hostname': hostname or socket.gethostname()
    }
    if reply_port is not None:
        payload['reply_port'] = int(reply_port)
    return json.dumps(payload).encode('utf-8')


def parse_response(data_bytes):
    return json.loads(data_bytes.decode('utf-8'))
