"""Testes de roundtrip dos payloads da Sprint 2 (apresentação, QUERY, STATUS, ACK)."""

from src.heartbeat import messaging


def test_roundtrip_apresentacao_local():
    obj = {"WORKER": "ALIVE", "WORKER_UUID": "W-123"}
    assert messaging.decode_message(messaging.encode_message(obj)) == obj


def test_roundtrip_apresentacao_emprestado():
    obj = {"WORKER": "ALIVE", "WORKER_UUID": "W-999", "SERVER_UUID": "Master-B"}
    assert messaging.decode_message(messaging.encode_message(obj)) == obj


def test_roundtrip_query_e_status():
    for obj in (
        {"TASK": "QUERY", "USER": "Michel"},
        {"TASK": "NO_TASK"},
        {"STATUS": "OK", "TASK": "QUERY", "WORKER_UUID": "W-123"},
        {"STATUS": "ACK", "WORKER_UUID": "W-123"},
    ):
        assert messaging.decode_message(messaging.encode_message(obj)) == obj
