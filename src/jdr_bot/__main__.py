"""Console entry point with sanitized failures and graceful shutdown."""

import asyncio
import logging
import signal

from pydantic import ValidationError

from jdr_bot.bot import TeamBot
from jdr_bot.config import Settings
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
                bot.start(settings.discord_bot_token.get_secret_value())
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
            if isinstance(results[0], Exception):
                raise RuntimeError("Discord startup or connection failed") from None
    finally:
        await engine.dispose()


def main() -> None:
    """Validate settings before connecting; avoid logging raw exceptions or secrets."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        settings = Settings()
    except ValidationError as error:
        fields = sorted({str(item["loc"][0]) for item in error.errors()})
        logger.error("invalid_configuration fields=%s; check .env.example", ",".join(fields))
        raise SystemExit(2) from None
    try:
        asyncio.run(run(settings))
    except Exception:
        logger.error("startup_failed; check credentials, connectivity, permissions, and migrations")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
