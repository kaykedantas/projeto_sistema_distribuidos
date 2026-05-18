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
