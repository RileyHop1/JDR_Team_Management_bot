"""Verify client failure and termination release owned tasks and resources."""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock

import pytest

from jdr_bot.__main__ import main, run


async def test_connection_failure_disposes_pool(settings, monkeypatch):
    engine = SimpleEngine()
    bot = MagicMock()
    bot.__aenter__ = AsyncMock(return_value=bot)
    bot.__aexit__ = AsyncMock(return_value=False)
    bot.start = AsyncMock(side_effect=RuntimeError("synthetic connection failure"))
    bot.close = AsyncMock()
    monkeypatch.setattr("jdr_bot.__main__.create_engine", lambda _: engine)
    monkeypatch.setattr("jdr_bot.__main__.TeamBot", lambda *_: bot)
    with pytest.raises(RuntimeError, match="connection failed"):
        await run(settings)
    bot.close.assert_awaited_once()
    engine.dispose.assert_awaited_once()


async def test_termination_cancels_connection_and_disposes_pool(settings, monkeypatch):
    engine = SimpleEngine()
    stopped = asyncio.Event()
    handlers = {}
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        loop, "add_signal_handler", lambda sig, callback: handlers.update({sig: callback})
    )
    monkeypatch.setattr(loop, "remove_signal_handler", lambda sig: handlers.pop(sig))

    async def connect(_):
        handlers[signal.SIGTERM]()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    bot = MagicMock()
    bot.__aenter__ = AsyncMock(return_value=bot)
    bot.__aexit__ = AsyncMock(return_value=False)
    bot.start = connect
    bot.close = AsyncMock()
    monkeypatch.setattr("jdr_bot.__main__.create_engine", lambda _: engine)
    monkeypatch.setattr("jdr_bot.__main__.TeamBot", lambda *_: bot)
    await run(settings)
    assert stopped.is_set()
    assert handlers == {}
    engine.dispose.assert_awaited_once()


class SimpleEngine:
    def __init__(self):
        self.dispose = AsyncMock()


def test_invalid_startup_logs_only_field_names(monkeypatch, caplog):
    from pydantic import ValidationError

    from jdr_bot.config import Settings

    def invalid_settings():
        raise ValidationError.from_exception_data(
            Settings.__name__,
            [{"type": "int_parsing", "loc": ("discord_guild_id",), "input": "private-input"}],
        )

    monkeypatch.setattr("jdr_bot.__main__.Settings", invalid_settings)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "discord_guild_id" in caplog.text
    assert "private-input" not in caplog.text
