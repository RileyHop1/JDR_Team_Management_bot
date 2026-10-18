"""One tracked poll loop for reminder jobs and the morning-brief job type."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from jdr_bot.policy import POLL_INTERVAL_SECONDS

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]


class JobPoller(Protocol):
    async def run_once(self) -> None:
        """Handle due work once. Storage failures may propagate."""


class ApplicationScheduler:
    """Poll reminders and, when configured, the brief. Shutdown cancels this task."""

    def __init__(
        self,
        reminders: JobPoller,
        briefs: JobPoller | None,
        *,
        poll_interval: float = POLL_INTERVAL_SECONDS,
        sleeper: Sleep | None = None,
    ) -> None:
        self._reminders = reminders
        self._briefs = briefs
        self._poll_interval = poll_interval
        self._sleep = asyncio.sleep if sleeper is None else sleeper

    async def serve(self) -> None:
        """Run until cancelled. A failure in one job type does not stop the other."""
        while True:
            try:
                await self._reminders.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("reminder_scheduler_failed error_type=%s", type(exc).__name__)
            if self._briefs is not None:
                try:
                    await self._briefs.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("brief_scheduler_failed error_type=%s", type(exc).__name__)
            await self._sleep(self._poll_interval)
