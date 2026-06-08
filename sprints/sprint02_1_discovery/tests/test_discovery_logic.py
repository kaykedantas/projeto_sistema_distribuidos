"""Testes da lógica pura de descoberta: eleição determinística e parsing."""

from src.heartbeat import discovery


def test_elege_menor_nome_lexicografico():
    replies = [
        {"TYPE": "DISCOVERY_REPLY", "MASTER_NAME": "MASTER_2", "MASTER_IP": "1.1.1.2", "MASTER_PORT": 8000},
        {"TYPE": "DISCOVERY_REPLY", "MASTER_NAME": "MASTER_1", "MASTER_IP": "1.1.1.1", "MASTER_PORT": 8000},
        {"TYPE": "DISCOVERY_REPLY", "MASTER_NAME": "MASTER_3", "MASTER_IP": "1.1.1.3", "MASTER_PORT": 8000},
    ]
    assert discovery.elect_master(replies)["MASTER_NAME"] == "MASTER_1"


def test_ordenacao_natural_master10_depois_de_master2():
    replies = [
        {"TYPE": "DISCOVERY_REPLY", "MASTER_NAME": "MASTER_10", "MASTER_IP": "1.1.1.10", "MASTER_PORT": 8000},
        {"TYPE": "DISCOVERY_REPLY", "MASTER_NAME": "MASTER_2", "MASTER_IP": "1.1.1.2", "MASTER_PORT": 8000},
    ]
    assert discovery.elect_master(replies)["MASTER_NAME"] == "MASTER_2"


def test_elect_vazio_retorna_none():
    assert discovery.elect_master([]) is None


def test_parse_reply_valida_ok():
    raw = {"TYPE": "DISCOVERY_REPLY", "MASTER_NAME": "MASTER_1",
           "MASTER_IP": "1.1.1.1", "MASTER_PORT": 8000, "STATUS": "AVAILABLE"}
    assert discovery.parse_reply(raw)["MASTER_NAME"] == "MASTER_1"


def test_parse_reply_sem_master_port_descarta():  # CT05
    raw = {"TYPE": "DISCOVERY_REPLY", "MASTER_NAME": "MASTER_1", "MASTER_IP": "1.1.1.1"}
    assert discovery.parse_reply(raw) is None


def test_parse_reply_ignora_campos_extras():
    raw = {"TYPE": "DISCOVERY_REPLY", "MASTER_NAME": "MASTER_1", "MASTER_IP": "1.1.1.1",
           "MASTER_PORT": 8000, "EXTRA": "x"}
    assert discovery.parse_reply(raw)["MASTER_PORT"] == 8000


def test_elect_ignora_invalidos_e_elege_valido():
    replies = [
        {"TYPE": "DISCOVERY_REPLY", "MASTER_NAME": "MASTER_5", "MASTER_IP": "1.1.1.5"},  # sem porta
        {"TYPE": "DISCOVERY_REPLY", "MASTER_NAME": "MASTER_4", "MASTER_IP": "1.1.1.4", "MASTER_PORT": 8000},
    ]
    eleito = discovery.elect_master(replies)
    assert eleito["MASTER_NAME"] == "MASTER_4"
