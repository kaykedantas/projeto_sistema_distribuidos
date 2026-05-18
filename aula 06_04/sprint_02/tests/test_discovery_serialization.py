import json
from src.discovery.worker_discovery import make_discovery_message, parse_response


def test_serialization_roundtrip():
    msg = make_discovery_message(worker_id='test-worker', hostname='host', reply_port=12345)
    assert isinstance(msg, bytes)
    obj = json.loads(msg.decode('utf-8'))
    assert obj['type'] == 'discovery' and obj['version'] == 1

    resp = {
        'type': 'discovery_response',
        'version': 1,
        'master_id': 'master-1',
        'hostname': 'master01'
    }
    data = json.dumps(resp).encode('utf-8')
    parsed = parse_response(data)
    assert parsed['master_id'] == 'master-1'
