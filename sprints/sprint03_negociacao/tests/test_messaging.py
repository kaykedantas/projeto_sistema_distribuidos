"""Testes de unidade do módulo de mensageria (JSON delimitado por \\n)."""

import json

from src.heartbeat import messaging


def test_encode_termina_com_newline():
    encoded = messaging.encode_message({"TASK": "HEARTBEAT"})
    assert isinstance(encoded, bytes)
    assert encoded.endswith(b"\n")


def test_encode_decode_roundtrip():
    obj = {"SERVER_UUID": "Master_A", "TASK": "HEARTBEAT"}
    encoded = messaging.encode_message(obj)
    decoded = messaging.decode_message(encoded)
    assert decoded == obj


def test_decode_aceita_str_e_bytes():
    obj = {"RESPONSE": "ALIVE"}
    linha = json.dumps(obj) + "\n"
    assert messaging.decode_message(linha) == obj
    assert messaging.decode_message(linha.encode("utf-8")) == obj


def test_payload_oficial_heartbeat_resposta():
    # Confere que o formato bate exatamente com o payload do plano.
    resp = {"SERVER_UUID": "Master_A", "TASK": "HEARTBEAT", "RESPONSE": "ALIVE"}
    assert messaging.decode_message(messaging.encode_message(resp)) == resp
