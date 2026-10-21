"""Сценарий для обычного пользователя: старт → выбор материала → проверка подписки → выдача."""
import html
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import keyboards as kb
from config import Config
from content import ContentStore, Material
from db import Database

router = Router(name="user")
log = logging.getLogger(__name__)

# Кэш file_id: после первой отправки файл не загружается в Telegram повторно
_file_id_cache: dict[str, str] = {}


async def is_subscribed(bot: Bot, channel_id: str, user_id: int) -> bool | None:
    """True/False — подписан ли пользователь. None — проверить не удалось
    (например, бот не админ канала). Если канал не задан, проверка отключена."""
    if not channel_id:
        return True
    try:
        member = await bot.get_chat_member(channel_id, user_id)
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        log.error("Не удалось проверить подписку (бот должен быть админом канала %s): %s", channel_id, e)
        return None
    if member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
        return True
    # Пользователь с ограничениями, но всё ещё в канале
    return member.status == ChatMemberStatus.RESTRICTED and getattr(member, "is_member", False)


async def send_material(message: Message, material: Material, store: ContentStore) -> bool:
    """Отправляет материал. Возвращает False, если файл не найден."""
    content = store.current
    if material.type == "link":
        open_kb = InlineKeyboardBuilder()
        open_kb.button(text="▶️ Открыть", url=material.url)
        await message.answer(material.caption or material.button, reply_markup=open_kb.as_markup())
        return True

    path = content.file_path(material.file)
    cache_key = str(path)
    if cache_key in _file_id_cache:
        media = _file_id_cache[cache_key]
    elif path.exists():
        media = FSInputFile(path)
    else:
        log.error("Файл материала «%s» не найден: %s", material.id, path)
        return False

    send = {"document": message.answer_document, "video": message.answer_video, "photo": message.answer_photo}
    sent = await send[material.type](media, caption=material.caption or None)

    # Запоминаем file_id, который выдал Telegram
    obj = {"document": sent.document, "video": sent.video, "photo": sent.photo[-1] if sent.photo else None}
    if obj[material.type]:
        _file_id_cache[cache_key] = obj[material.type].file_id
    return True


async def give_material(
    message: Message, user_id: int, material: Material, store: ContentStore, db: Database
) -> None:
    content = store.current
    if not await send_material(message, material, store):
        await message.answer("😔 Этот материал временно недоступен. Мы уже чиним!")
        return
    await db.log_download(user_id, material.id)
    await message.answer(content.text("after_material"), reply_markup=kb.after_material_kb(content, material.id))


# ---------- /start ----------

@router.message(CommandStart())
async def cmd_start(message: Message, store: ContentStore, db: Database) -> None:
    user = message.from_user
    is_new = await db.add_user(user.id, user.username, user.full_name)
    if is_new:
        log.info("Новый пользователь: %s (%s)", user.id, user.username)

    content = store.current
    if content.welcome_video_note:
        path = content.file_path(content.welcome_video_note)
        if path.exists():
            try:
                await message.answer_video_note(FSInputFile(path))
            except TelegramBadRequest as e:  # кружок должен быть квадратным mp4 до 60 сек
                log.warning("Не удалось отправить видеокружок: %s", e)

    await message.answer(
        content.text("welcome", name=html.escape(user.first_name or "друг")),
        reply_markup=kb.main_menu(),
    )
    await message.answer(content.text("choose"), reply_markup=kb.materials_kb(content))


# ---------- постоянное меню ----------

@router.message(F.text == kb.MENU_MATERIALS)
async def menu_materials(message: Message, store: ContentStore) -> None:
    await message.answer(store.current.text("choose"), reply_markup=kb.materials_kb(store.current))


@router.message(F.text == kb.MENU_LINKS)
async def menu_links(message: Message, store: ContentStore) -> None:
    await message.answer(store.current.text("links"), reply_markup=kb.links_kb(store.current))


@router.callback_query(F.data == "links")
async def cb_links(call: CallbackQuery, store: ContentStore) -> None:
    await call.answer()
    await call.message.answer(store.current.text("links"), reply_markup=kb.links_kb(store.current))


# ---------- выбор материала ----------

@router.callback_query(F.data.startswith("mat:"))
async def cb_material(call: CallbackQuery, bot: Bot, store: ContentStore, db: Database, config: Config) -> None:
    material = store.current.material(call.data.split(":", 1)[1])
    if material is None:  # кнопка из старого сообщения, материал удалён
        await call.answer("Этот материал больше недоступен", show_alert=True)
        return
    await call.answer()

    # Если пользователь пришёл не через /start (например, после очистки базы) — сохраним его
    await db.add_user(call.from_user.id, call.from_user.username, call.from_user.full_name)

    subscribed = await is_subscribed(bot, config.channel_id, call.from_user.id)
    if subscribed is False:
        await call.message.answer(
            store.current.text("need_subscribe"),
            reply_markup=kb.subscribe_kb(config.channel_url, material.id),
        )
        return
    if subscribed is None:
        await call.message.answer(store.current.text("check_error"))
    await give_material(call.message, call.from_user.id, material, store, db)


@router.callback_query(F.data.startswith("chk:"))
async def cb_check_subscription(
    call: CallbackQuery, bot: Bot, store: ContentStore, db: Database, config: Config
) -> None:
    material = store.current.material(call.data.split(":", 1)[1])
    if material is None:
        await call.answer("Этот материал больше недоступен", show_alert=True)
        return

    subscribed = await is_subscribed(bot, config.channel_id, call.from_user.id)
    if subscribed is False:
        await call.answer(store.current.text("not_subscribed"), show_alert=True)
        return
    await call.answer("Спасибо за подписку! 🎉")
    # Убираем кнопки «Подписаться / Я подписался», чтобы не нажимали повторно
    try:
        await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
    except TelegramBadRequest:
        pass
    await give_material(call.message, call.from_user.id, material, store, db)


# ---------- всё остальное ----------

@router.message()
async def fallback(message: Message, store: ContentStore) -> None:
    await message.answer(store.current.text("choose"), reply_markup=kb.materials_kb(store.current))
