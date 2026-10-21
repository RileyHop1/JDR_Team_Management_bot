"""Console entry point with sanitized failures and graceful shutdown."""

import asyncio
import logging
import signal
from typing import NoReturn

from pydantic import ValidationError

from jdr_bot.bot import TeamBot, start_client
from jdr_bot.config import Settings
from jdr_bot.startup import StartupFailure, configuration_failure
from jdr_bot.storage import create_engine

logger = logging.getLogger(__name__)


async def run(settings: Settings) -> None:
    """Own Discord, signal handlers, and the database pool for the process lifetime."""
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        async with TeamBot(settings, engine) as bot:
            loop = asyncio.get_running_loop()
            stop = asyncio.Event()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stop.set)
            client_task = asyncio.create_task(
                start_client(bot, settings.discord_bot_token.get_secret_value())
            )
            stop_task = asyncio.create_task(stop.wait())
            try:
                await asyncio.wait((client_task, stop_task), return_when=asyncio.FIRST_COMPLETED)
            finally:
                try:
                    await bot.close()
                finally:
                    for task in (client_task, stop_task):
                        if not task.done():
                            task.cancel()
                    results = await asyncio.gather(client_task, stop_task, return_exceptions=True)
                    for sig in (signal.SIGINT, signal.SIGTERM):
                        loop.remove_signal_handler(sig)
            # Keep the original error so main can classify it by type.
            # Wrapping it would hide that type and could repeat a credential.
            client_result = results[0]
            if isinstance(client_result, Exception):
                raise client_result
    finally:
        await engine.dispose()


def main() -> None:
    """Validate settings before connecting; log categories, not secrets or driver text."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        settings = Settings()
    except ValidationError as error:
        _exit_for_startup_failure(configuration_failure(error))
    except StartupFailure as failure:
        _exit_for_startup_failure(failure)
    try:
        asyncio.run(run(settings))
    except StartupFailure as failure:
        _exit_for_startup_failure(failure)
    except Exception as error:
        logger.error(
            "startup_failed error_type=%s; check credentials, connectivity, permissions, "
            "and migrations",
            type(error).__name__,
        )
        raise SystemExit(1) from None


def _exit_for_startup_failure(failure: StartupFailure) -> NoReturn:
    logger.error("%s", failure)
    raise SystemExit(failure.exit_code) from None


if __name__ == "__main__":
    main()
