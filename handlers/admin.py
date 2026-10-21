"""Админ-панель: статистика, рассылка, выгрузка пользователей, обновление контента."""
import asyncio
import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

import keyboards as kb
from content import ContentStore
from db import Database

log = logging.getLogger(__name__)

# Пауза между сообщениями рассылки: Telegram разрешает ~30 сообщений в секунду
BROADCAST_DELAY = 0.05


class Broadcast(StatesGroup):
    waiting_message = State()
    confirm = State()


def get_admin_router(admin_ids: set[int]) -> Router:
    router = Router(name="admin")
    # Все хендлеры этого роутера срабатывают только для админов
    router.message.filter(F.from_user.id.in_(admin_ids))
    router.callback_query.filter(F.from_user.id.in_(admin_ids))

    @router.message(Command("admin"))
    async def cmd_admin(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("⚙️ <b>Админ-панель</b>", reply_markup=kb.admin_kb())

    @router.message(Command("cancel"), StateFilter("*"))
    async def cmd_cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Отменено.", reply_markup=kb.admin_kb())

    # ---------- статистика ----------
    @router.callback_query(F.data == "adm:stats")
    async def cb_stats(call: CallbackQuery, db: Database, store: ContentStore) -> None:
        await call.answer()
        s = await db.stats()
        names = {m.id: m.button for m in store.current.materials}
        downloads = "\n".join(
            f"  • {names.get(mid, mid)}: <b>{cnt}</b>" for mid, cnt in s["downloads"].items()
        ) or "  пока нет"
        await call.message.answer(
            "📊 <b>Статистика</b>\n\n"
            f"Всего пользователей: <b>{s['total']}</b>\n"
            f"Активных (не заблокировали бота): <b>{s['active']}</b>\n"
            f"Новых за 24 часа: <b>{s['new_day']}</b>\n"
            f"Новых за 7 дней: <b>{s['new_week']}</b>\n\n"
            f"Выдано материалов:\n{downloads}"
        )

    # ---------- выгрузка ----------
    @router.callback_query(F.data == "adm:export")
    async def cb_export(call: CallbackQuery, db: Database) -> None:
        await call.answer("Готовлю файл…")
        data = await db.export_csv()
        name = f"users_{datetime.now():%Y-%m-%d}.csv"
        await call.message.answer_document(BufferedInputFile(data, filename=name), caption="Пользователи бота")

    # ---------- обновление контента ----------
    @router.callback_query(F.data == "adm:reload")
    async def cb_reload(call: CallbackQuery, store: ContentStore) -> None:
        try:
            content = store.reload()
        except ValueError as e:
            await call.answer()
            await call.message.answer(f"❌ Контент не обновлён, старая версия продолжает работать.\n\n{e}")
            return
        await call.answer("Контент обновлён ✅", show_alert=True)
        log.info("Контент перезагружен: %d материалов", len(content.materials))

    # ---------- рассылка ----------
    @router.callback_query(F.data == "adm:broadcast")
    async def cb_broadcast_start(call: CallbackQuery, state: FSMContext) -> None:
        await call.answer()
        await state.set_state(Broadcast.waiting_message)
        await call.message.answer(
            "📨 Пришлите сообщение для рассылки — текст, фото, видео или файл с подписью.\n"
            "Оно будет скопировано всем пользователям как есть.\n\n/cancel — отмена"
        )

    @router.message(Broadcast.waiting_message)
    async def broadcast_got_message(message: Message, state: FSMContext, db: Database) -> None:
        await state.update_data(from_chat_id=message.chat.id, message_id=message.message_id)
        await state.set_state(Broadcast.confirm)
        count = len(await db.active_user_ids())
        await message.answer("👆 Так увидят сообщение пользователи.")
        await message.send_copy(message.chat.id)
        await message.answer(f"Отправить <b>{count}</b> пользователям?", reply_markup=kb.confirm_broadcast_kb())

    @router.callback_query(Broadcast.confirm, F.data == "bc:cancel")
    async def broadcast_cancel(call: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await call.answer("Рассылка отменена")
        await call.message.edit_text("❌ Рассылка отменена.")

    @router.callback_query(Broadcast.confirm, F.data == "bc:send")
    async def broadcast_send(call: CallbackQuery, state: FSMContext, bot: Bot, db: Database) -> None:
        data = await state.get_data()
        await state.clear()
        await call.answer()
        user_ids = await db.active_user_ids()
        progress = await call.message.edit_text(f"⏳ Рассылка началась: 0 / {len(user_ids)}")

        sent = blocked = failed = 0
        for i, uid in enumerate(user_ids, start=1):
            result = await _copy_with_retry(bot, uid, data["from_chat_id"], data["message_id"])
            if result == "ok":
                sent += 1
            elif result == "blocked":
                blocked += 1
                await db.set_inactive(uid)
            else:
                failed += 1
            if i % 50 == 0:  # обновляем прогресс не слишком часто
                try:
                    await progress.edit_text(f"⏳ Рассылка: {i} / {len(user_ids)}")
                except TelegramBadRequest:
                    pass
            await asyncio.sleep(BROADCAST_DELAY)

        log.info("Рассылка завершена: отправлено %d, заблокировали %d, ошибок %d", sent, blocked, failed)
        await progress.edit_text(
            "✅ <b>Рассылка завершена</b>\n\n"
            f"Доставлено: <b>{sent}</b>\n"
            f"Заблокировали бота: <b>{blocked}</b>\n"
            f"Другие ошибки: <b>{failed}</b>"
        )

    return router


async def _copy_with_retry(bot: Bot, chat_id: int, from_chat_id: int, message_id: int) -> str:
    """Копирует сообщение пользователю. Возвращает 'ok', 'blocked' или 'error'."""
    for _ in range(3):
        try:
            await bot.copy_message(chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id)
            return "ok"
        except TelegramRetryAfter as e:  # слишком часто — Telegram просит подождать
            await asyncio.sleep(e.retry_after)
        except TelegramForbiddenError:  # пользователь заблокировал бота
            return "blocked"
        except TelegramBadRequest as e:
            log.warning("Рассылка: не удалось отправить %s: %s", chat_id, e)
            return "error"
    return "error"
