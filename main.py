import logging
import asyncio

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

import config
from handlers import accounts, invitations, scraping, settings


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        handlers=[logging.FileHandler("bot.log", encoding='utf-8'), logging.StreamHandler()]
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting bot initialization...")

    redis_url = f"redis://{config.REDIS_HOST}:{config.REDIS_PORT}/{config.REDIS_DB}"
    storage = RedisStorage.from_url(redis_url)
    logger.info(f"Redis storage connected to {redis_url}")

    bot = Bot(token=config.BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=storage)
    logger.info("Bot and Dispatcher initialized.")

    logger.info("Registering handlers...")
    accounts.register_handlers(dp)
    invitations.register_handlers(dp)
    scraping.register_handlers(dp)
    settings.register_handlers(dp)
    logger.info("Handlers registered.")

    logger.info("Bot started polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    if not hasattr(config, 'AUTH_TIMEOUT_SEC'):
        config.AUTH_TIMEOUT_SEC = 600
    asyncio.run(main())
