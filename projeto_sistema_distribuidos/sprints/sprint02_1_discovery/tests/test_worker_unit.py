"""Testes de unidade do executor do Worker (process_task)."""

import asyncio

from src.heartbeat import worker_async


def test_process_task_ok_quando_forcado():
    res = asyncio.run(worker_async.process_task("Michel", force="OK",
                                                min_delay=0, max_delay=0))
    assert res == "OK"


def test_process_task_nok_quando_forcado():
    res = asyncio.run(worker_async.process_task("Julia", force="NOK",
                                                min_delay=0, max_delay=0))
    assert res == "NOK"
