"""The shared poll loop keeps running when one job type fails."""

import asyncio
import logging

import pytest

from jdr_bot.scheduler import ApplicationScheduler


class CountingPoller:
    def __init__(self) -> None:
        self.runs = 0

    async def run_once(self) -> None:
        self.runs += 1


class BoomPoller:
    async def run_once(self) -> None:
        raise RuntimeError("synthetic-secret")


async def test_brief_failure_does_not_stop_reminders(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.ERROR)
    reminders = CountingPoller()
    briefs = BoomPoller()

    async def stop(_: float) -> None:
        raise asyncio.CancelledError

    scheduler = ApplicationScheduler(reminders, briefs, sleeper=stop)
    with pytest.raises(asyncio.CancelledError):
        await scheduler.serve()
    assert reminders.runs == 1
    assert "RuntimeError" in caplog.text
    assert "synthetic-secret" not in caplog.text
