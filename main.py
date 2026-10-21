"""Точка входа: python main.py"""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat

from config import load_config
from content import ContentStore
from db import Database
from handlers import admin, user


async def set_commands(bot: Bot, admin_ids: set[int]) -> None:
    await bot.set_my_commands([BotCommand(command="start", description="Начать / меню")])
    for admin_id in admin_ids:  # админам дополнительно показываем /admin
        try:
            await bot.set_my_commands(
                [
                    BotCommand(command="start", description="Начать / меню"),
                    BotCommand(command="admin", description="Админ-панель"),
                ],
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception as e:  # админ ещё не запускал бота
            logging.warning("Не удалось задать команды для админа %s: %s", admin_id, e)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    config = load_config()
    store = ContentStore(config.content_path)  # ошибка в content.json остановит запуск с понятным текстом
    db = Database(config.db_path)

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # Объекты ниже автоматически попадают в хендлеры по имени аргумента (store, db, config)
    dp = Dispatcher(storage=MemoryStorage(), store=store, db=db, config=config)
    dp.include_router(admin.get_admin_router(config.admin_ids))  # админ-роутер первым
    dp.include_router(user.router)

    if not config.admin_ids:
        logging.warning("ADMIN_IDS не задан — админ-панель недоступна")
    if not config.channel_id:
        logging.warning("CHANNEL_ID не задан — проверка подписки отключена")

    try:
        await set_commands(bot, config.admin_ids)
        await bot.delete_webhook(drop_pending_updates=True)
        me = await bot.get_me()
        logging.info("Бот @%s запущен", me.username)
        await dp.start_polling(bot)
    finally:
        db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен")
