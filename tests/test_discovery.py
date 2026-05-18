import json
from src.discovery import make_discovery_payload, parse_discovery_reply

def test_make_discovery_payload_contains_type():
    p = make_discovery_payload("W-101")
    assert b'DISCOVERY' in p

def test_parse_discovery_reply_valid():
    raw = b'{"TYPE":"DISCOVERY_REPLY","MASTER_NAME":"MASTER_1","MASTER_IP":"192.168.1.20","MASTER_PORT":6000,"STATUS":"AVAILABLE"}'
    obj = parse_discovery_reply(raw)
    assert obj['MASTER_NAME'] == 'MASTER_1'
