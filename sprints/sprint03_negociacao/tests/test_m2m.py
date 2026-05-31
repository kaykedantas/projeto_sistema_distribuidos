"""Testes do envelope M2M e construtores dos 7 tipos de mensagem (Sprint 3)."""

import uuid

from src.heartbeat import m2m


def test_request_id_e_uuid_v4():
    rid = m2m.new_request_id()
    assert uuid.UUID(rid).version == 4


def test_make_message_envelope():
    msg = m2m.make_message("request_help", {"x": 1}, request_id="r1")
    assert msg == {"type": "request_help", "request_id": "r1", "payload": {"x": 1}}


def test_make_message_gera_request_id_quando_ausente():
    msg = m2m.make_message("ping", {})
    assert uuid.UUID(msg["request_id"]).version == 4


def test_request_help_payload():
    msg = m2m.request_help("A", current_load=150, capacity=100, workers_needed=2)
    assert msg["type"] == "request_help"
    assert msg["payload"] == {"master_id": "A", "current_load": 150,
                               "capacity": 100, "workers_needed": 2}


def test_response_accepted_mantem_request_id():
    msg = m2m.response_accepted([{"id": "B1", "address": "ip:1"}], request_id="r9")
    assert msg["request_id"] == "r9"
    assert msg["payload"]["workers_offered"] == 1
    assert msg["payload"]["worker_details"][0]["id"] == "B1"


def test_response_rejected_reason_valido():
    msg = m2m.response_rejected("high_load", request_id="r9")
    assert msg["payload"]["reason"] == "high_load"


def test_command_redirect_e_register_e_release_e_notify():
    assert m2m.command_redirect("ip_a:8000")["type"] == "command_redirect"
    assert m2m.register_temporary_worker("B1", "ip_b:8000")["type"] == "register_temporary_worker"
    assert m2m.command_release("ip_b:8000")["type"] == "command_release"
    assert m2m.notify_worker_returned("B1")["type"] == "notify_worker_returned"
