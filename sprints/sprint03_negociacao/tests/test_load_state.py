"""Testes do estado de carga e detecção de saturação com histerese (Sprint 3)."""

from src.heartbeat import master_async


def test_set_load_detecta_saturacao():
    m = master_async.Master("127.0.0.1", 0, capacity=100, release_threshold=60)
    eventos = []
    m.on_saturation = lambda needed: eventos.append(("sat", needed))
    m.on_release = lambda: eventos.append(("rel",))
    m.set_load(150)
    assert eventos and eventos[0][0] == "sat"


def test_set_load_detecta_liberacao_com_histerese():
    m = master_async.Master("127.0.0.1", 0, capacity=100, release_threshold=60)
    estados = []
    m.on_saturation = lambda needed: estados.append("sat")
    m.on_release = lambda: estados.append("rel")
    m.set_load(150)   # satura
    m.set_load(80)    # entre 60 e 100: NÃO libera (histerese)
    assert "rel" not in estados
    m.set_load(50)    # < release_threshold: libera
    assert "rel" in estados


def test_workers_needed_proporcional_ao_excedente():
    m = master_async.Master("127.0.0.1", 0, capacity=100, release_threshold=60)
    assert m.compute_workers_needed(150) >= 1
    assert m.compute_workers_needed(300) >= m.compute_workers_needed(150)
