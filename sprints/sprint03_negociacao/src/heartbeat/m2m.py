"""
m2m.py — Envelope e construtores das mensagens Master-to-Master (Sprint 3).

Toda mensagem M2M segue o envelope padrão do projeto:

    {"type": "<tipo>", "request_id": "<uuid_v4>", "payload": { ... }}

terminado por ``\\n`` no fio (o ``messaging`` cuida disso). O ``request_id`` é
um UUID v4 que correlaciona requisição e resposta mesmo em conexões concorrentes.
Os valores de ``type`` são sempre minúsculos, exatamente como no PDF.
"""

import uuid

# Motivos válidos para response_rejected (Nota do PDF).
REASONS = {"high_load", "no_workers_available", "refused"}


def new_request_id() -> str:
    """Gera um UUID v4 em formato string."""
    return str(uuid.uuid4())


def make_message(type_, payload, request_id=None):
    """Monta o envelope padrão; gera ``request_id`` se não informado."""
    return {
        "type": type_,
        "request_id": request_id or new_request_id(),
        "payload": payload or {},
    }


def request_help(master_id, current_load, capacity, workers_needed, request_id=None):
    """Master A → Master B: pedido de Workers emprestados."""
    return make_message("request_help", {
        "master_id": master_id,
        "current_load": current_load,
        "capacity": capacity,
        "workers_needed": workers_needed,
    }, request_id)


def response_accepted(worker_details, request_id=None):
    """Master B → Master A: aceita e informa os Workers ofertados.

    ``worker_details`` é uma lista de dicts ``{"id", "address"}``.
    """
    return make_message("response_accepted", {
        "workers_offered": len(worker_details),
        "worker_details": worker_details,
    }, request_id)


def response_rejected(reason, request_id=None):
    """Master B → Master A: recusa o pedido, informando o motivo."""
    return make_message("response_rejected", {"reason": reason}, request_id)


def command_redirect(new_master_address, request_id=None):
    """Master B → Worker: ordena reportar-se ao Master saturado."""
    return make_message("command_redirect",
                        {"new_master_address": new_master_address}, request_id)


def register_temporary_worker(worker_id, original_master_address, request_id=None):
    """Worker → Master A: apresenta-se como emprestado, indicando a origem."""
    return make_message("register_temporary_worker", {
        "worker_id": worker_id,
        "original_master_address": original_master_address,
    }, request_id)


def command_release(original_master_address, request_id=None):
    """Master A → Worker: libera o Worker para retornar ao Master original."""
    return make_message("command_release",
                        {"original_master_address": original_master_address}, request_id)


def notify_worker_returned(worker_id, request_id=None):
    """Master A → Master B: notifica que o Worker emprestado foi devolvido."""
    return make_message("notify_worker_returned", {"worker_id": worker_id}, request_id)
